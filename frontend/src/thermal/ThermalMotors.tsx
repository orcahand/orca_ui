// One tile per motor — live temperature, current and shaft position, which
// motor it is coupled to, whether it is in the test, and during a run the
// state the operation reports for it — plus the pairs editor underneath:
// which motors are joined shaft to shaft, and whether the partner pushes
// opposed or the same way. Readouts are written into the DOM from the 10 Hz
// motors.state stream; the rest re-renders at the operation's rate.

import { useRef } from 'react'
import { useEffect } from 'react'
import { api } from '../api/rest'
import type {
  PairDiscoveryExtra,
  ThermalExtra,
  ThermalMotorReport,
  ThermalMotorState,
} from '../api/types'
import { type BenchMotor, useBenchStore } from '../bench/benchStore'
import { formatDeg, formatMa, useMotorLive } from '../bench/useMotorLive'
import { useAppStore } from '../state/appStore'
import { useOperationActive, useOperationStore } from '../state/operationStore'
import { checkPair, MAX_STEP_DEG, MIN_STEP_DEG } from './pairCheck'
import { type MotorPair, pairKey, pairsInOrder, partnerOf, useThermalStore } from './thermalStore'

const STATE_LABEL: Record<ThermalMotorState, string> = {
  driving: 'driving',
  cooling: 'cooling',
  limit: 'cut · too hot',
  slipped: 'cut · slipped',
  done: 'done',
}

function tempClass(t: number | undefined, limit: number): string {
  if (t === undefined || Number.isNaN(t)) return ''
  if (t >= limit) return 'err'
  if (t >= limit - 10) return 'warn'
  return 'ok'
}

function Tile({
  motor,
  connected,
  report,
  limit,
  running,
  pair,
  free,
  numberOf,
}: {
  motor: BenchMotor
  connected: boolean
  report: ThermalMotorReport | null
  limit: number
  running: boolean
  pair: MotorPair | null
  free: boolean
  numberOf: (id: number) => number | string
}) {
  const included = useThermalStore((s) => s.motors[motor.id]?.included ?? true)
  const setIncluded = useThermalStore((s) => s.setIncluded)
  const held = useAppStore((s) => s.control?.held_motors?.includes(motor.id) ?? false)
  const tempRef = useRef<HTMLSpanElement>(null)
  const curRef = useRef<HTMLSpanElement>(null)
  const posRef = useRef<HTMLSpanElement>(null)
  const id = String(motor.id)

  useMotorLive((frames) => {
    const t = frames.motors.temps[id]
    if (tempRef.current) {
      tempRef.current.textContent = t === undefined ? '—' : `${t.toFixed(0)}°`
      tempRef.current.className = `thermal-temp ${tempClass(t, limit)}`
    }
    if (curRef.current) curRef.current.textContent = formatMa(frames.motors.currents[id])
    if (posRef.current) posRef.current.textContent = formatDeg(frames.motors.positions[id], 0)
  })

  const partner = pair ? (pair.a === motor.id ? pair.b : pair.a) : null
  const inverted = pair !== null && pair.b === motor.id && pair.opposed
  const state = report?.state ?? null
  const cut = state === 'limit' || state === 'slipped'
  const classes = [
    'thermal-tile',
    included ? '' : 'excluded',
    cut ? 'cut' : '',
    report && running && state === 'driving' ? 'driving' : '',
    pair || free ? '' : 'unpaired',
  ].join(' ')

  return (
    <div className={classes} title={`bus id ${motor.id}${held ? ' · held' : ' · released'}`}>
      <div className="thermal-tile-head">
        <label className="thermal-include" title={pair ? 'in the test (with its partner)' : 'in the test'}>
          <input
            type="checkbox"
            checked={included}
            disabled={running}
            onChange={(e) => setIncluded(motor.id, e.target.checked)}
          />
          <b>M{motor.number}</b>
        </label>
        {partner !== null ? (
          <span
            className={`thermal-pair ${inverted ? 'inverted' : ''}`}
            title={
              inverted
                ? `coupled to M${numberOf(partner)}; this one's current is inverted so the two push against each other`
                : `coupled to M${numberOf(partner)}`
            }
          >
            ↔ M{numberOf(partner)}
            {inverted && <small> −</small>}
          </span>
        ) : free ? (
          <span className="thermal-pair" title="free: the motor turns with the waveform">
            free
          </span>
        ) : (
          <span className="thermal-pair none" title="no load partner — it will spin unless clamped some other way">
            no partner
          </span>
        )}
        <span className={`thermal-held ${held ? 'on' : ''}`}>{held ? 'held' : 'free'}</span>
      </div>
      <span ref={tempRef} className="thermal-temp">
        —
      </span>
      <div className="thermal-tile-side">
        <span ref={curRef}>—</span>
        <span ref={posRef}>—</span>
      </div>
      {report && (
        <div className={`thermal-state ${state ?? ''}`}>
          {state ? STATE_LABEL[state] : ''}
          {report.via_partner && <small> (partner)</small>}
          {report.rise_c !== null && (
            <small>
              {' '}
              {report.rise_c >= 0 ? '+' : ''}
              {report.rise_c.toFixed(0)}°
            </small>
          )}
          {state === 'driving' && <small> {Math.round(report.goal_ma)} mA</small>}
          {report.drift_deg !== null && Math.abs(report.drift_deg) >= 1 && (
            <small className={!free && Math.abs(report.drift_deg) > 10 ? 'err' : ''}>
              {' '}
              {free ? 'moved' : 'drift'} {report.drift_deg.toFixed(0)}°
            </small>
          )}
        </div>
      )}
      {!connected && <div className="thermal-state">offline</div>}
    </div>
  )
}

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 90) return 'just now'
  if (s < 5400) return `${Math.round(s / 60)} min ago`
  if (s < 172800) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

function PairsEditor({
  motors,
  running,
  connected,
}: {
  motors: BenchMotor[]
  running: boolean
  connected: boolean
}) {
  const pairs = useThermalStore((s) => s.pairs)
  const setPairs = useThermalStore((s) => s.setPairs)
  const checks = useThermalStore((s) => s.checks)
  const stepDeg = useThermalStore((s) => s.settings.pairStepDeg)
  const patchSettings = useThermalStore((s) => s.patchSettings)
  const reload = useThermalStore((s) => s.reload)
  const checking = useThermalStore((s) => s.checking)
  const setChecking = useThermalStore((s) => s.setChecking)
  const setCheck = useThermalStore((s) => s.setCheck)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const operation = useOperationStore((s) => s.operation)
  const discovery = operation?.kind === 'pair_discovery' ? operation : null
  const discovering = discovery !== null && opActive
  const discoveryExtra = (discovery?.extra ?? null) as PairDiscoveryExtra | null
  // A finished discovery wrote the pairs on the backend: take them over.
  useEffect(() => {
    if (discovery && discovery.state === 'done') void reload()
  }, [discovery, discovery?.state, reload])
  const numberOf = (id: number) => motors.find((m) => m.id === id)?.number ?? id
  const label = (id: number) => `M${numberOf(id)}`
  const used = new Set(pairs.flatMap((p) => [p.a, p.b]))
  const free = motors.filter((m) => !used.has(m.id))
  const held = control?.held_motors ?? []

  const discoverBlocked: string | null = !connected
    ? 'no motor bus'
    : opActive
      ? 'a run is in progress'
      : control && control.control_source !== 'manual'
        ? `control is owned by ${control.control_owner}`
        : checking
          ? 'a check is running'
          : motors.length < 2
            ? 'two motors at least'
            : null

  const checkBlocked = (pair: MotorPair): string | null => {
    if (!connected) return 'no motor bus'
    if (opActive) return 'a run is in progress'
    if (control && control.control_source !== 'manual') return `control is owned by ${control.control_owner}`
    if (checking) return 'a check is running'
    if (!held.includes(pair.a) || !held.includes(pair.b)) return 'hold both motors first'
    return null
  }

  const runCheck = async (pair: MotorPair) => {
    const key = pairKey(pair)
    setChecking(key)
    setCheck(key, null)
    try {
      const result = await checkPair(pair, label, stepDeg)
      setCheck(key, result)
      if (result.error) setError(result.error)
      else {
        setError(null)
        // The check knows which way the partner turns: same way means the
        // two must be driven opposed to load each other.
        if (result.ok) {
          const checked = { at: new Date().toISOString(), sense: result.sense as 1 | -1 }
          setPairs(
            useThermalStore
              .getState()
              .pairs.map((p) => (pairKey(p) === key ? { ...p, opposed: result.sense > 0, checked } : p)),
          )
          setCheck(key, result)
        }
      }
    } finally {
      setChecking(null)
    }
  }

  const checkAll = async () => {
    for (const pair of pairs) {
      if (checkBlocked(pair)) break
      await runCheck(pair)
    }
  }

  // Changing who is in a pair voids its check; flipping "opposed" does not.
  const update = (index: number, patch: Partial<MotorPair>) =>
    setPairs(
      pairs.map((p, i) =>
        i === index ? { ...p, ...patch, ...('a' in patch || 'b' in patch ? { checked: undefined } : {}) } : p,
      ),
    )
  const remove = (index: number) => setPairs(pairs.filter((_, i) => i !== index))
  const add = () => {
    if (free.length < 2) return
    setPairs([...pairs, { a: free[0].id, b: free[1].id, opposed: true }])
  }
  // A select offers the motor it holds plus every free one, so swapping two
  // motors between pairs is two picks, not a remove and an add.
  const options = (current: number) =>
    motors.filter((m) => m.id === current || !used.has(m.id)).map((m) => (
      <option key={m.id} value={m.id}>
        M{m.number} (id {m.id})
      </option>
    ))

  return (
    <div className="thermal-pairs">
      <div className="thermal-pairs-head">
        <span className="thermal-group-title">coupled pairs — each motor is the other's load</span>
        <div className="thermal-pairs-actions">
          <button
            className={`btn btn-primary ${discovering ? 'busy' : ''}`}
            disabled={discoverBlocked !== null}
            title={
              discoverBlocked ??
              `find the pairs by moving: every motor is released, then each in turn is held and turned ${stepDeg}° left and right while the other shafts are watched — whichever follows is its partner, and the way it follows sets "opposed". Replaces the pairs below.`
            }
            onClick={() =>
              void api
                .operationStart('pair_discovery', { step_deg: stepDeg })
                .then(() => setError(null))
                .catch((error) => setError(String((error as Error).message ?? error)))
            }
          >
            {discovering ? '… finding pairs' : '⌕ Find pairs'}
          </button>
          <label
            className="stress-field"
            title="how far a motor is turned, each way, when finding or checking a pair — more than the coupling's backlash, less than anything can hit"
          >
            turn by
            <input
              type="number"
              min={MIN_STEP_DEG}
              max={MAX_STEP_DEG}
              step={1}
              value={stepDeg}
              disabled={running || discovering || checking !== null}
              onChange={(e) => {
                const v = parseFloat(e.target.value)
                if (Number.isFinite(v) && v >= MIN_STEP_DEG && v <= MAX_STEP_DEG) patchSettings({ pairStepDeg: v })
              }}
            />
            °
          </label>
          <button
            className="btn btn-secondary"
            disabled={running || motors.length < 2}
            title="pair motors in number order: 1↔2, 3↔4, …"
            onClick={() => setPairs(pairsInOrder(motors))}
          >
            pair in order
          </button>
          <button className="btn btn-secondary" disabled={running || free.length < 2} onClick={add}>
            + pair
          </button>
          <button className="btn btn-secondary" disabled={running || pairs.length === 0} onClick={() => setPairs([])}>
            clear
          </button>
          <button
            className="btn btn-secondary"
            disabled={pairs.length === 0 || pairs.some((p) => checkBlocked(p) !== null)}
            title={
              pairs.length === 0
                ? 'no pairs'
                : (pairs.map(checkBlocked).find((b) => b !== null) ??
                  `check every pair in turn: each motor turns ${stepDeg}° left and right while its partner is released`)
            }
            onClick={() => void checkAll()}
          >
            check all
          </button>
        </div>
      </div>
      {discovering && (
        <div className="thermal-pairs-note live">
          {discoveryExtra?.mover !== null && discoveryExtra?.mover !== undefined
            ? `turning M${numberOf(discoveryExtra.mover)}, watching the others…`
            : 'releasing the motors…'}
          {discoveryExtra && discoveryExtra.pairs.length > 0 && (
            <>
              {' '}
              found so far: {discoveryExtra.pairs.map((p) => `M${numberOf(p.a)}↔M${numberOf(p.b)}`).join(', ')}
            </>
          )}
        </div>
      )}
      {pairs.length > 0 && (
        <div className="thermal-pairs-list">
          {pairs.map((pair, i) => (
            <div key={`${pair.a}-${pair.b}`} className="thermal-pair-row">
              <select value={pair.a} disabled={running} onChange={(e) => update(i, { a: parseInt(e.target.value, 10) })}>
                {options(pair.a)}
              </select>
              <span className="thermal-pair-link">↔</span>
              <select value={pair.b} disabled={running} onChange={(e) => update(i, { b: parseInt(e.target.value, 10) })}>
                {options(pair.b)}
              </select>
              <label
                className="stress-field bench-check"
                title={`invert M${numberOf(pair.b)}'s current so the two push against each other. Face to face on one coupler the same sign already opposes; through a belt or gears it does not — the fixture decides. If a pair spins, flip this.`}
              >
                <input
                  type="checkbox"
                  checked={pair.opposed}
                  disabled={running}
                  onChange={(e) => update(i, { opposed: e.target.checked })}
                />
                opposed
              </label>
              <button
                className={`btn btn-secondary thermal-pair-check ${checking === pairKey(pair) ? 'busy' : ''}`}
                disabled={checkBlocked(pair) !== null}
                title={
                  checkBlocked(pair) ??
                  `M${numberOf(pair.a)} turns ${stepDeg}° left and right while M${numberOf(pair.b)} is released, then the other way round — a coupled partner follows, and which way it follows sets "opposed"`
                }
                onClick={() => void runCheck(pair)}
              >
                {checking === pairKey(pair) ? '… checking' : 'check'}
              </button>
              <button className="btn btn-secondary thermal-pair-remove" disabled={running} title="unpair" onClick={() => remove(i)}>
                ×
              </button>
              {!checks[pairKey(pair)] && pair.checked && (
                <span className="thermal-pair-result ok" title={new Date(pair.checked.at).toLocaleString()}>
                  ✓ checked {ago(pair.checked.at)} — {pair.checked.sense > 0 ? 'same direction' : 'opposite directions'}
                </span>
              )}
              {!checks[pairKey(pair)] && !pair.checked && (
                <span className="thermal-pair-result dim">unchecked</span>
              )}
              {checks[pairKey(pair)] && (
                <span
                  className={`thermal-pair-result ${checks[pairKey(pair)].ok ? 'ok' : 'err'}`}
                  title={checks[pairKey(pair)].followed
                    .map((f) => `M${numberOf(f.mover)} moved, M${numberOf(f.partner)} followed ${f.deg.toFixed(1)}°`)
                    .join('\n')}
                >
                  {checks[pairKey(pair)].ok ? '✓ ' : '✗ '}
                  {checks[pairKey(pair)].error ?? checks[pairKey(pair)].message}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {free.length > 0 && (
        <div className="thermal-pairs-note">
          {free.length === motors.length
            ? 'No pairs yet: a motor driven against nothing just spins and is cut for slipping.'
            : `Without a partner: ${free.map((m) => `M${m.number}`).join(', ')} — fine only if clamped some other way.`}
        </div>
      )}
    </div>
  )
}

export function ThermalMotors({ connected }: { connected: boolean }) {
  const motors = useBenchStore((s) => s.motors)
  const limit = useThermalStore((s) => s.settings.tempLimitC)
  const pairs = useThermalStore((s) => s.pairs)
  const free = useThermalStore((s) => s.settings.load === 'free')
  const setAllIncluded = useThermalStore((s) => s.setAllIncluded)
  const operation = useOperationStore((s) => s.operation)
  const active = useOperationActive()
  const ours = operation?.kind === 'motor_thermal'
  const extra = ours ? ((operation?.extra ?? null) as ThermalExtra | null) : null
  const running = ours && active
  const reports = new Map((extra?.motors ?? []).map((m) => [m.id, m]))
  const numberOf = (id: number) => motors.find((m) => m.id === id)?.number ?? id

  if (motors.length === 0) {
    return (
      <section className="panel panel-empty">
        {connected
          ? 'The connected config names no motors — scan the bus above.'
          : 'Waiting for the motor bus… power the motors, plug in the adapter, or scan to see what answers.'}
      </section>
    )
  }

  return (
    <section className="panel thermal-motors">
      <div className="panel-header">
        <h2>Motors</h2>
        <span className="panel-hint">
          {motors.length} on the bus
          {free ? ' · free' : ` · ${pairs.length} pair${pairs.length === 1 ? '' : 's'}`} · temperature now, current, shaft position
        </span>
        <div className="header-spacer" />
        <button className="btn btn-secondary" disabled={running} onClick={() => setAllIncluded(true)}>
          all in
        </button>
        <button className="btn btn-secondary" disabled={running} onClick={() => setAllIncluded(false)}>
          none
        </button>
      </div>
      <div className="thermal-grid">
        {motors.map((motor) => (
          <Tile
            key={motor.id}
            motor={motor}
            connected={connected}
            report={reports.get(motor.id) ?? null}
            limit={extra?.temp_limit_c ?? limit}
            running={running}
            pair={free ? null : partnerOf(pairs, motor.id)}
            free={free}
            numberOf={numberOf}
          />
        ))}
      </div>
      {!free && <PairsEditor motors={motors} running={running} connected={connected} />}
    </section>
  )
}

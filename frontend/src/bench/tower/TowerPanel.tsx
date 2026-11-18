// The motor tower as the bench's map. Clicking motors selects them (shift
// adds), and the cycle and thermal panels then show and run only the
// selection. Identify numbers the motors by where they sit: every motor is
// released, a slot is armed, the operator turns that motor by hand, and the
// shaft that moved is the motor in that slot. Saving rewrites the bench's
// motor numbers so slot NN is motor NN; the servos keep their bus ids.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useOperationActive } from '../../state/operationStore'
import { type BenchMotor, useBenchStore } from '../benchStore'
import { JOG_STEPS_DEG, useJog } from '../useJog'
import { formatDeg, formatMa, useMotorLive } from '../useMotorLive'
import {
  assignmentsFor,
  candidates as candidatesOf,
  type Movement,
  movements,
  place,
  slotsOf,
  STILL_DEG,
  TURN_DEG,
  turnedMotor,
} from './identify'
import { loadTower, type Tower } from './towerModel'
import { TowerScene } from './TowerScene'

const OPEN_KEY = 'orca-ui.bench.tower.open'
// After a motor is found, wait until every shaft has been this still for
// SETTLE_SAMPLES samples before arming the next slot, so the hand still on
// the last motor does not answer for the next one.
const SETTLE_DEG = 0.5
const SETTLE_SAMPLES = 6

function storedOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) !== '0'
  } catch {
    return true
  }
}

function Inspector({ motor, enabled }: { motor: BenchMotor; enabled: boolean }) {
  const held = useAppStore((s) => s.control?.held_motors?.includes(motor.id) ?? false)
  const setError = useAppStore((s) => s.setError)
  const [step, setStep] = useState(JOG_STEPS_DEG[1])
  const [busy, setBusy] = useState(false)
  const livePos = useRef<number | null>(null)
  const pos = useRef<HTMLSpanElement>(null)
  const cur = useRef<HTMLSpanElement>(null)
  const temp = useRef<HTMLSpanElement>(null)
  const fault = useRef<HTMLDivElement>(null)
  const key = String(motor.id)
  useMotorLive((frames) => {
    const p = frames.motors.positions[key]
    livePos.current = p ?? null
    if (pos.current) pos.current.textContent = formatDeg(p)
    if (cur.current) cur.current.textContent = formatMa(frames.motors.currents[key])
    if (temp.current) {
      const t = frames.motors.temps[key]
      temp.current.textContent = t === undefined ? '—' : `${t.toFixed(0)} °C`
    }
    if (fault.current) {
      const hw = frames.motors.faults?.motors[key]?.hw_error
      fault.current.textContent = hw ? `${hw.headline} — ${hw.advice}` : ''
    }
  })
  const { jogging, startRepeat, stopRepeat } = useJog(motor.id, livePos, step, enabled && held)

  const toggleHold = async () => {
    setBusy(true)
    try {
      await api.motorTorque(motor.id, !held)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const jog = (direction: 1 | -1) => ({
    onPointerDown: () => startRepeat(direction),
    onPointerUp: stopRepeat,
    onPointerLeave: stopRepeat,
  })

  return (
    <div className="tower-inspector">
      <div className="tower-inspector-head">
        <h3>Motor {motor.number}</h3>
        <span>bus id {motor.id}</span>
      </div>
      <dl className="tower-readout">
        <dt>shaft</dt>
        <dd><span ref={pos}>—</span></dd>
        <dt>current</dt>
        <dd><span ref={cur}>—</span></dd>
        <dt>temp</dt>
        <dd><span ref={temp}>—</span></dd>
      </dl>
      <div className="tower-fault" ref={fault} />
      <div className="tower-actions">
        <button
          className={`btn ${held ? 'btn-secondary' : 'btn-primary'}`}
          disabled={!enabled || busy}
          onClick={() => void toggleHold()}
        >
          {held ? 'Release' : 'Hold'}
        </button>
        <button className="btn btn-secondary" disabled={!enabled || !held} {...jog(-1)}>
          − {step}°
        </button>
        <button className="btn btn-secondary" disabled={!enabled || !held} {...jog(1)}>
          + {step}°
        </button>
        <select value={step} onChange={(e) => setStep(Number(e.target.value))} title="jog step">
          {JOG_STEPS_DEG.map((s) => (
            <option key={s} value={s}>
              {s}°
            </option>
          ))}
        </select>
        {jogging && <span className="tower-note">jogging…</span>}
      </div>
      {!held && <p className="tower-note">Hold it to jog. Released, it turns by hand.</p>}
    </div>
  )
}

function SelectionTools({ picked, enabled }: { picked: BenchMotor[]; enabled: boolean }) {
  const setError = useAppStore((s) => s.setError)
  const setSelected = useBenchStore((s) => s.setSelected)
  const [busy, setBusy] = useState(false)
  const hold = async (on: boolean) => {
    setBusy(true)
    try {
      for (const m of picked) await api.motorTorque(m.id, on)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="tower-inspector">
      <div className="tower-inspector-head">
        <h3>{picked.length} motors</h3>
      </div>
      <div className="tower-chips">
        {picked.map((m) => (
          <span key={m.id} className="bench-bus-chip">
            <b>{m.number}</b> id {m.id}
          </span>
        ))}
      </div>
      <div className="tower-actions">
        <button className="btn btn-primary" disabled={!enabled || busy} onClick={() => void hold(true)}>
          Hold these
        </button>
        <button className="btn btn-secondary" disabled={!enabled || busy} onClick={() => void hold(false)}>
          Release these
        </button>
        <button className="btn btn-secondary" onClick={() => setSelected([])}>
          Clear
        </button>
      </div>
    </div>
  )
}

interface Identify {
  draft: Record<number, number>
  armed: number | null
  confirmed: number[]
  // The motor just found in the armed slot, waiting for Next or Redo, with
  // the draft as it was before so Redo can put it back.
  found: { slot: number; id: number; draft: Record<number, number>; confirmed: number[] } | null
}

export function TowerPanel({ connected }: { connected: boolean }) {
  const motors = useBenchStore((s) => s.motors)
  const selected = useBenchStore((s) => s.selected)
  const setSelected = useBenchStore((s) => s.setSelected)
  const toggleSelected = useBenchStore((s) => s.toggleSelected)
  const mode = useBenchStore((s) => s.mode)
  const scan = useBenchStore((s) => s.scan)
  const bench = useAppStore((s) => s.handInfo?.bench ?? false)
  const control = useAppStore((s) => s.control)
  const torque = useAppStore((s) => s.status?.torque_enabled ?? false)
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const [open, setOpen] = useState(storedOpen)
  const [tower, setTower] = useState<Tower | null>(null)
  const [failed, setFailed] = useState(false)
  const [identify, setIdentify] = useState<Identify | null>(null)
  const [saving, setSaving] = useState(false)
  // Shafts that moved together, for the operator to say which one was meant.
  const [candidates, setCandidates] = useState<Movement[]>([])
  const [manualId, setManualId] = useState('')

  useEffect(() => {
    let live = true
    loadTower()
      .then((t) => live && setTower(t))
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [])

  const toggleOpen = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(OPEN_KEY, o ? '0' : '1')
      } catch {
        /* storage disabled: the panel just opens every time */
      }
      return !o
    })
  }

  const slotCount = tower ? Math.max(...tower.slots.map((s) => s.slot)) : 0
  const benchSlots = useMemo(() => slotsOf(motors, slotCount), [motors, slotCount])
  const slots = identify?.draft ?? benchSlots
  const placedIds = new Set(Object.values(slots))
  const unplaced = motors.filter((m) => !placedIds.has(m.id))
  const offBench = (scan?.motor_ids ?? []).filter((id) => !motors.some((m) => m.id === id))
  const picked = motors.filter((m) => selected.includes(m.id))
  const manual = control?.control_source === 'manual'
  const canDrive = connected && manual && !opActive
  let identifyBlocked: string | null = null
  if (!bench) identifyBlocked = 'the config in force is a hand model'
  else if (!connected) identifyBlocked = 'no motor bus'
  else if (opActive) identifyBlocked = 'a run is in progress — stop it first'
  else if (!manual) identifyBlocked = `control is owned by ${control?.control_owner ?? 'someone else'}`
  else if (motors.length === 0) identifyBlocked = 'no motors on the bench — scan the bus'

  // Identification: a baseline per armed slot, compared on every sample.
  const baseline = useRef<Record<string, number> | null>(null)
  const settle = useRef<{ last: Record<string, number> | null; still: number }>({ last: null, still: 0 })
  const readout = useRef<HTMLSpanElement>(null)
  const identifyRef = useRef(identify)
  identifyRef.current = identify

  useMotorLive((frames) => {
    const state = identifyRef.current
    if (!state || state.armed === null || state.found !== null) return
    const positions = frames.motors.positions
    if (baseline.current === null) {
      const s = settle.current
      const last = s.last
      const quiet =
        last !== null &&
        Object.keys(positions).every((id) => Math.abs((positions[id] ?? 0) - (last[id] ?? 0)) < SETTLE_DEG)
      s.still = quiet ? s.still + 1 : 0
      s.last = { ...positions }
      if (readout.current) readout.current.textContent = 'waiting for the shafts to stop…'
      if (s.still >= SETTLE_SAMPLES) baseline.current = { ...positions }
      return
    }
    const moved = movements(baseline.current, positions)
    if (readout.current) {
      const top = moved.slice(0, 2).filter((m) => m.deg >= 1)
      readout.current.textContent = top.length
        ? top.map((m) => `id ${m.id} ${m.deg.toFixed(0)}°`).join(' · ')
        : 'nothing turning yet'
    }
    const several = candidatesOf(moved).map((m) => ({ id: m.id, deg: Math.round(m.deg) }))
    setCandidates((now) =>
      now.length === several.length && now.every((m, i) => m.id === several[i].id && m.deg === several[i].deg)
        ? now
        : several,
    )
    const id = turnedMotor(moved)
    if (id !== null) assign(id)
  })

  // The armed slot holds `id` now: found by turning, picked among several
  // that turned, or set by hand. Next or Redo follows either way.
  const assign = (id: number) => {
    const state = identifyRef.current
    if (!state || state.armed === null) return
    const slot = state.armed
    setCandidates([])
    setIdentify({
      ...state,
      draft: place(state.draft, slot, id),
      confirmed: [...state.confirmed.filter((s) => s !== slot), slot],
      found: { slot, id, draft: state.draft, confirmed: state.confirmed },
    })
  }

  // Forget what has turned so far: the next baseline is taken once every
  // shaft is still again.
  const rebaseline = () => {
    baseline.current = null
    settle.current = { last: null, still: 0 }
    setCandidates([])
  }

  const arm = (slot: number | null) => {
    rebaseline()
    setIdentify((s) => (s ? { ...s, armed: slot, found: null } : s))
  }

  const next = () => {
    if (!identify || !tower) return
    const order = tower.slots.map((s) => s.slot)
    const from = identify.found?.slot ?? identify.armed ?? 0
    const unchecked = (s: number) => !identify.confirmed.includes(s)
    arm(order.find((s) => s > from && unchecked(s)) ?? order.find(unchecked) ?? null)
  }

  const redo = () => {
    if (!identify?.found) return
    const { slot, draft, confirmed } = identify.found
    rebaseline()
    setIdentify({ ...identify, draft, confirmed, armed: slot, found: null })
  }

  // Keys, so a hand on the tower needs only the keyboard: Enter for next,
  // Backspace to redo or reset.
  useEffect(() => {
    if (!identify) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return
      if (e.key === 'Enter' && identify.found) {
        e.preventDefault()
        next()
      } else if (e.key === 'Backspace') {
        e.preventDefault()
        if (identify.found) redo()
        else rebaseline()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const startIdentify = async () => {
    if (identifyBlocked || !tower) return
    if (torque) {
      if (!window.confirm('Identifying releases every motor so they turn by hand. Continue?')) return
      try {
        await api.torqueDisable()
      } catch (error) {
        setError(String((error as Error).message ?? error))
        return
      }
    }
    rebaseline()
    setSelected([])
    setIdentify({ draft: benchSlots, armed: tower.slots[0]?.slot ?? null, confirmed: [], found: null })
  }

  const save = async () => {
    if (!identify) return
    setSaving(true)
    try {
      await api.benchMotors(assignmentsFor(motors, identify.draft, slotCount))
      setIdentify(null)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setSaving(false)
    }
  }

  const onPick = (slot: number, additive: boolean) => {
    if (identify) {
      arm(slot)
      return
    }
    const id = slots[slot]
    if (id === undefined) return
    if (additive) toggleSelected(id)
    else setSelected(selected.length === 1 && selected[0] === id ? [] : [id])
  }

  const changed =
    identify !== null &&
    (Object.keys(identify.draft).length !== Object.keys(benchSlots).length ||
      Object.entries(identify.draft).some(([s, id]) => benchSlots[Number(s)] !== id))
  const heldNow = control?.held_motors?.length ?? 0
  const narrows = mode === 'fingers' ? '' : ` · ${mode} shows only these`

  return (
    <section className="panel bench-tower">
      <div className="bench-bus-head">
        <button
          type="button"
          className="bench-bus-toggle"
          aria-expanded={open}
          onClick={toggleOpen}
          title={open ? 'fold the tower' : 'unfold the tower'}
        >
          <span className={`bench-chevron ${open ? 'open' : ''}`}>▸</span>
          <h2>Tower</h2>
        </button>
        {identify ? (
          <>
            <button className="btn btn-info" disabled={!changed || saving || opActive} onClick={() => void save()}>
              {saving ? 'Saving…' : 'Save numbering'}
            </button>
            <button className="btn btn-secondary" disabled={saving} onClick={() => setIdentify(null)}>
              Cancel
            </button>
          </>
        ) : (
          <button
            className="btn btn-primary"
            disabled={identifyBlocked !== null || !tower}
            title={identifyBlocked ?? 'release every motor and find each slot\'s motor by turning it by hand'}
            onClick={() => void startIdentify()}
          >
            Identify motors
          </button>
        )}
        <span className="bench-bus-summary">
          {identify
            ? `${identify.confirmed.length} of ${tower?.slots.length ?? 0} slots checked${changed ? ' · unsaved' : ''}`
            : `${Object.keys(benchSlots).length} of ${tower?.slots.length ?? '…'} slots filled` +
              (unplaced.length ? ` · ${unplaced.length} not on the tower` : '') +
              (picked.length ? ` · ${picked.length} selected${narrows}` : '')}
        </span>
      </div>

      {open && (
        <div className="tower-body">
          <div className="tower-canvas">
            {tower ? (
              <TowerScene
                tower={tower}
                slots={slots}
                selected={selected}
                identifying={identify !== null}
                armed={identify?.armed ?? null}
                confirmed={identify?.confirmed ?? []}
                onPick={onPick}
              />
            ) : (
              <p className="tower-note">
                {failed
                  ? 'The tower model is missing. Build it with scripts/build_bench_tower.py.'
                  : 'Loading the tower…'}
              </p>
            )}
          </div>

          <div className="tower-side">
            {identify ? (
              <div className="tower-inspector">
                {identify.found ? (
                  <>
                    <h3 className="tower-found">
                      ✓ Slot {identify.found.slot} is id {identify.found.id}
                    </h3>
                    {identify.found.draft[identify.found.slot] !== undefined &&
                      identify.found.draft[identify.found.slot] !== identify.found.id && (
                        <p className="tower-note">
                          It was id {identify.found.draft[identify.found.slot]} before.
                        </p>
                      )}
                    <div className="tower-actions">
                      <button className="btn btn-primary" onClick={next} title="Enter">
                        Next slot ⏎
                      </button>
                      <button
                        className="btn btn-secondary"
                        onClick={redo}
                        title="wrong motor? forget it and turn slot again (Backspace)"
                      >
                        Redo slot {identify.found.slot}
                      </button>
                    </div>
                  </>
                ) : identify.armed === null ? (
                  <>
                    <h3>Every slot checked</h3>
                    <p className="tower-note">
                      Save to number the motors by slot, or click a slot to check it again.
                    </p>
                  </>
                ) : (
                  <>
                    <h3>Turn the motor in slot {identify.armed}</h3>
                    <p className="tower-note">
                      By hand, at least {TURN_DEG}°, with the others still (under {STILL_DEG}°).
                      Click another slot to do that one instead.
                    </p>
                    <p className="tower-live">
                      <span ref={readout}>waiting for the shafts to stop…</span>
                    </p>
                    {candidates.length > 0 && (
                      <div className="tower-candidates">
                        <p className="tower-warn">More than one turned — which is in slot {identify.armed}?</p>
                        <div className="tower-actions">
                          {candidates.map((m) => (
                            <button key={m.id} className="btn btn-info" onClick={() => assign(m.id)}>
                              id {m.id} · {m.deg}°
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="tower-actions">
                      <select
                        value={manualId}
                        onChange={(e) => setManualId(e.target.value)}
                        title="pair a bus id with this slot without turning it"
                      >
                        <option value="">set id by hand…</option>
                        {[...motors]
                          .sort((a, b) => a.id - b.id)
                          .map((m) => {
                            const at = Object.entries(identify.draft).find(([, id]) => id === m.id)?.[0]
                            return (
                              <option key={m.id} value={m.id}>
                                id {m.id}
                                {at === undefined ? ' · not placed' : ` · in slot ${at}`}
                              </option>
                            )
                          })}
                      </select>
                      <button
                        className="btn btn-secondary"
                        disabled={manualId === ''}
                        onClick={() => {
                          assign(Number(manualId))
                          setManualId('')
                        }}
                      >
                        Pair
                      </button>
                    </div>
                    <div className="tower-actions">
                      <button
                        className="btn btn-secondary"
                        onClick={rebaseline}
                        title="ignore what has turned so far — start counting from where the shafts are now (Backspace)"
                      >
                        Reset
                      </button>
                      <button className="btn btn-secondary" onClick={next} title="leave this slot for now">
                        Skip
                      </button>
                    </div>
                  </>
                )}
                {heldNow > 0 && (
                  <p className="tower-warn">
                    {heldNow} motor{heldNow === 1 ? ' is' : 's are'} held and will not turn — release
                    them in the bar above.
                  </p>
                )}
                {unplaced.length > 0 && (
                  <p className="tower-note">
                    Not in a slot yet: {unplaced.map((m) => `id ${m.id}`).join(', ')}
                  </p>
                )}
                {!identify.found && identify.armed !== null && identify.draft[identify.armed] !== undefined && (
                  <div className="tower-actions">
                    <button
                      className="btn btn-secondary"
                      onClick={() => {
                        const draft = { ...identify.draft }
                        delete draft[identify.armed as number]
                        setIdentify({ ...identify, draft })
                      }}
                    >
                      Empty slot {identify.armed}
                    </button>
                  </div>
                )}
              </div>
            ) : picked.length === 1 ? (
              <Inspector key={picked[0].id} motor={picked[0]} enabled={canDrive} />
            ) : picked.length > 1 ? (
              <SelectionTools picked={picked} enabled={canDrive} />
            ) : (
              <div className="tower-inspector">
                <p className="tower-note">
                  Click a motor to select it; shift-click adds more. Cycle and Thermal then show
                  and run only the selection. A motor glows while its shaft turns.
                </p>
                {unplaced.length > 0 && (
                  <p className="tower-note">
                    Not on the tower: {unplaced.map((m) => `motor ${m.number} (id ${m.id})`).join(', ')}{' '}
                    — Identify motors to place them.
                  </p>
                )}
              </div>
            )}
            {offBench.length > 0 && (
              <p className="tower-warn">
                The last scan also found {offBench.map((id) => `id ${id}`).join(', ')}, not on the
                bench — add {offBench.length === 1 ? 'it' : 'them'} in the Bus panel to place{' '}
                {offBench.length === 1 ? 'it' : 'them'}.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

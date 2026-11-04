// The test definition and the run buttons. Everything the operation
// validates is gated here too, so Start says why it is off instead of
// bouncing a 409: the motors must be held, and |offset| + amplitude must fit
// under the current ceiling set in the bar above.

import { useMemo, useState } from 'react'
import { api } from '../api/rest'
import type { ThermalExtra, ThermalLoad, ThermalWaveform } from '../api/types'
import { useBenchStore } from '../bench/benchStore'
import { subscribeFrames } from '../state/streamStore'
import { useAppStore } from '../state/appStore'
import { isOperationActive, operationLabel, useOperationStore } from '../state/operationStore'
import { useEffect } from 'react'
import {
  peakMa,
  partnerOf,
  runParams,
  selectedMotors,
  selectedFree,
  selectedPairs,
  supplyPeakMa,
  type ThermalSettings,
  useThermalStore,
} from './thermalStore'

function WavePreview({ s, ceiling }: { s: ThermalSettings; ceiling: number | null }) {
  const w = 220
  const h = 56
  const top = Math.max(peakMa(s), ceiling ?? 0, 1)
  const y = (ma: number) => h / 2 - (ma / top) * (h / 2 - 3)
  const points: string[] = []
  const periods = 2
  for (let i = 0; i <= 200; i++) {
    const t = (i / 200) * periods
    let v = s.offsetMa
    if (s.waveform === 'sine') v += s.amplitudeMa * Math.sin(2 * Math.PI * t)
    else if (s.waveform === 'square') v += t % 1 < 0.5 ? s.amplitudeMa : -s.amplitudeMa
    points.push(`${((i / 200) * w).toFixed(1)},${y(v).toFixed(1)}`)
  }
  const periodS = s.waveform === 'constant' ? null : 1 / s.frequencyHz
  return (
    <svg className="thermal-wave" viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden>
      {ceiling !== null && (
        <>
          <line x1={0} x2={w} y1={y(ceiling)} y2={y(ceiling)} className="ceiling" />
          <line x1={0} x2={w} y1={y(-ceiling)} y2={y(-ceiling)} className="ceiling" />
        </>
      )}
      <line x1={0} x2={w} y1={h / 2} y2={h / 2} className="zero" />
      <polyline points={points.join(' ')} className="trace" />
      <text x={w - 2} y={h - 3} textAnchor="end" className="label">
        {periodS !== null ? `${periods} periods · ${periodS.toFixed(2)} s each` : 'constant'}
      </text>
    </svg>
  )
}

export function ThermalSetup({ connected }: { connected: boolean }) {
  const s = useThermalStore((st) => st.settings)
  const patch = useThermalStore((st) => st.patchSettings)
  const setup = useThermalStore((st) => st.motors)
  const pairs = useThermalStore((st) => st.pairs)
  const motors = useBenchStore((st) => st.motors)
  const free = s.load === 'free'
  const selected = useMemo(
    () => (free ? selectedFree(motors, setup) : selectedMotors(motors, setup, pairs)),
    [free, motors, setup, pairs],
  )
  const unpaired = free ? [] : selected.filter((m) => partnerOf(pairs, m.id) === null)
  // Phase slots as the backend assigns them: one per pair, one per lone motor.
  const slotSizes = useMemo(() => {
    const seen = new Set<number>()
    const sizes: number[] = []
    for (const m of selected) {
      if (seen.has(m.id)) continue
      seen.add(m.id)
      const pair = free ? null : partnerOf(pairs, m.id)
      const other = pair ? (pair.a === m.id ? pair.b : pair.a) : null
      if (other !== null && selected.some((x) => x.id === other) && !seen.has(other)) {
        seen.add(other)
        sizes.push(2)
      } else sizes.push(1)
    }
    return sizes
  }, [selected, pairs, free])
  const control = useAppStore((st) => st.control)
  const setError = useAppStore((st) => st.setError)
  const operation = useOperationStore((st) => st.operation)
  const [busy, setBusy] = useState(false)
  const [familyMax, setFamilyMax] = useState<number | null>(null)
  useEffect(
    () =>
      subscribeFrames((frames) => {
        if (frames.motors.maxTempC !== null && frames.motors.maxTempC !== familyMax)
          setFamilyMax(frames.motors.maxTempC)
      }),
    [familyMax],
  )

  const active = isOperationActive(operation)
  const ours = active && operation?.kind === 'motor_thermal'
  const paused = ours && operation?.state === 'paused'
  const log = ours ? ((operation?.extra as ThermalExtra | null)?.log ?? null) : null
  const logging = log ? log.on : s.logCsv
  const ceiling = control?.max_current ?? null
  const held = control?.held_motors ?? []
  const peak = peakMa(s)
  const maxTemp = familyMax ?? 70

  let blocked: string | null = null
  if (!connected) blocked = 'no motor bus'
  else if (active) blocked = `${operationLabel(operation!.kind)} is running`
  else if (control && control.control_source !== 'manual')
    blocked = `control is owned by ${control.control_owner}`
  else if (selected.length === 0) blocked = 'tick at least one motor'
  else if (peak <= 0) blocked = 'amplitude and offset are both zero'
  else if (ceiling !== null && peak > ceiling)
    blocked = `|offset| + amplitude is ${peak} mA — above the ${ceiling} mA ceiling`
  else {
    const loose = selected.filter((m) => !held.includes(m.id))
    if (loose.length > 0) {
      const names = loose.map((m) => motors.find((x) => x.id === m.id)?.number ?? m.id)
      blocked = loose.length === selected.length ? 'hold the motors first' : `hold motor ${names.join(', ')} first`
    }
  }

  const call = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const start = () =>
    call(() =>
      api.operationStart('motor_thermal', { ...runParams(selected, selectedPairs(selected, pairs), s) }),
    )
  const toggleLog = () => {
    const next = !logging
    patch({ logCsv: next })
    if (ours) void call(() => api.operationInput(next ? 'log on' : 'log off'))
  }

  const num = (key: keyof ThermalSettings, text: string, min: number, max: number) => {
    const v = parseFloat(text)
    if (Number.isFinite(v) && v >= min && v <= max) patch({ [key]: v } as Partial<ThermalSettings>)
  }
  const disabled = ours

  return (
    <section className="panel thermal-setup">
      <div className="panel-header">
        <h2>Test</h2>
        <span className="panel-hint">
          {selected.length} motor{selected.length === 1 ? '' : 's'} in
          {free
            ? ' · free, turning'
            : ` · ${selectedPairs(selected, pairs).length} pair${selectedPairs(selected, pairs).length === 1 ? '' : 's'}`}
        </span>
      </div>

      <div className="bench-run-buttons">
        {!ours ? (
          <button
            className="btn btn-primary bench-start"
            disabled={busy || blocked !== null}
            title={blocked ?? 'drive the ticked motors with this waveform and record their temperature'}
            onClick={() => void start()}
          >
            ▶ Start
          </button>
        ) : (
          <>
            <button
              className="btn btn-secondary"
              disabled={busy}
              title="pause keeps the current where it is — the motors stay hot"
              onClick={() => void call(() => (paused ? api.operationResume() : api.operationPause()))}
            >
              {paused ? '▶ Resume' : '❚❚ Pause'}
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={() => void call(() => api.operationStop())}>
              ■ Stop
            </button>
          </>
        )}
        {blocked && !ours && <span className="bench-blocked">{blocked}</span>}
        {!blocked && !ours && unpaired.length > 0 && (
          <span className="bench-blocked thermal-warn" title="a motor driven against nothing spins and is cut for slipping">
            ⚠ no load partner: {unpaired.map((m) => `M${motors.find((x) => x.id === m.id)?.number ?? m.id}`).join(', ')}
          </span>
        )}
        <label
          className={`bench-log-toggle ${logging ? 'on' : ''}`}
          title="write every sample (goal and actual current, position, drift, temperature) of every motor to a CSV in the model's logs/ folder"
        >
          <input type="checkbox" checked={logging} disabled={busy} onChange={toggleLog} />
          Log CSV
          {log && log.rows > 0 && (
            <small>
              {log.rows.toLocaleString()} rows
              {log.files.length > 1 && ` · ${log.files.length} files`}
            </small>
          )}
        </label>
      </div>

      <div className="thermal-fields">
        <div className="thermal-field-group">
          <span className="thermal-group-title">load</span>
          <div className="thermal-load">
            {(
              [
                ['coupled', 'coupled pairs', 'the shafts are blocked pairwise; each motor pushes against its partner with the waveform as its current limit'],
                ['free', 'free — the motors turn', 'nothing on the shafts: the servos run in current control for the run and turn back and forth with the signed waveform (round and round with an offset). Keep hands and cables clear.'],
              ] as [ThermalLoad, string, string][]
            ).map(([value, text, hint]) => (
              <label key={value} className={`thermal-load-option ${s.load === value ? 'on' : ''}`} title={hint}>
                <input
                  type="radio"
                  name="thermal-load"
                  checked={s.load === value}
                  disabled={disabled}
                  onChange={() => patch({ load: value })}
                />
                {text}
              </label>
            ))}
          </div>
          {free && (
            <div className="thermal-pairs-note">
              The motors will spin. Pairs are ignored; nothing is cut for moving.
            </div>
          )}
        </div>
        <div className="thermal-field-group">
          <span className="thermal-group-title">current waveform</span>
          <div className="bench-fields">
            <label className="stress-field">
              shape
              <select
                value={s.waveform}
                disabled={disabled}
                onChange={(e) => patch({ waveform: e.target.value as ThermalWaveform })}
              >
                <option value="sine">sine</option>
                <option value="square">square</option>
                <option value="constant">constant</option>
              </select>
            </label>
            <label className="stress-field" title="peak of the oscillation around the offset">
              amplitude
              <input
                type="number"
                min={0}
                max={ceiling ?? 2000}
                step={10}
                value={s.amplitudeMa}
                disabled={disabled || s.waveform === 'constant'}
                onChange={(e) => num('amplitudeMa', e.target.value, 0, 5000)}
              />
              mA
            </label>
            <label className="stress-field" title="bias the waveform sits on; negative pushes the other way">
              offset
              <input
                type="number"
                min={-(ceiling ?? 2000)}
                max={ceiling ?? 2000}
                step={10}
                value={s.offsetMa}
                disabled={disabled}
                onChange={(e) => num('offsetMa', e.target.value, -5000, 5000)}
              />
              mA
            </label>
            <label className="stress-field" title="0.01 to 5 Hz">
              frequency
              <input
                type="number"
                min={0.01}
                max={5}
                step={0.1}
                value={s.frequencyHz}
                disabled={disabled || s.waveform === 'constant'}
                onChange={(e) => num('frequencyHz', e.target.value, 0.01, 5)}
              />
              Hz
            </label>
          </div>
          <div className="thermal-wave-row">
            <WavePreview s={s} ceiling={ceiling} />
            <div className="thermal-peaks">
              <span className={`thermal-peak ${ceiling !== null && peak > ceiling ? 'err' : ''}`}>
                peak {peak} mA per motor
                {ceiling !== null && <small> / ceiling {ceiling} mA</small>}
              </span>
              {selected.length > 0 && (
                <span className="thermal-peak" title="highest sum of every motor's |current| over a period — what the supply has to deliver">
                  supply peak ≈ {(supplyPeakMa(s, slotSizes.length, slotSizes, s.stagger) / 1000).toFixed(2)} A
                  {s.stagger && slotSizes.length > 1 && s.waveform !== 'constant' && (
                    <small> (all in phase: {(supplyPeakMa(s, slotSizes.length, slotSizes, false) / 1000).toFixed(2)} A)</small>
                  )}
                </span>
              )}
            </div>
          </div>
          <label
            className="stress-field bench-check thermal-stagger"
            title="each pair runs the waveform at its own phase, the phases spread evenly, so the pairs peak in turn and the supply current stays flatter"
          >
            <input type="checkbox" checked={s.stagger} disabled={disabled || s.waveform === 'constant'} onChange={(e) => patch({ stagger: e.target.checked })} />
            stagger the {free ? "motors'" : "pairs'"} phases
          </label>
        </div>

        <div className="thermal-field-group">
          <span className="thermal-group-title">timing</span>
          <div className="bench-fields">
            <label className="stress-field" title="how long the current is applied">
              heat for
              <input
                type="number"
                min={0.1}
                max={1440}
                step={1}
                value={s.durationMin}
                disabled={disabled || s.loop}
                onChange={(e) => num('durationMin', e.target.value, 0.01, 1440)}
              />
              min
            </label>
            <label className="stress-field bench-check" title="heat until Stop is pressed, then cool down">
              <input type="checkbox" checked={s.loop} disabled={disabled} onChange={(e) => patch({ loop: e.target.checked })} />
              until stopped
            </label>
            <label className="stress-field" title="current off, temperature still recorded">
              then cool for
              <input
                type="number"
                min={0}
                max={1440}
                step={1}
                value={s.cooldownMin}
                disabled={disabled}
                onChange={(e) => num('cooldownMin', e.target.value, 0, 1440)}
              />
              min
            </label>
          </div>
        </div>

        <div className="thermal-field-group">
          <span className="thermal-group-title">cut a motor when</span>
          <div className="bench-fields">
            <label className="stress-field" title={`the motor stops being driven at this temperature; the family shuts itself down at ${maxTemp} °C`}>
              it reaches
              <input
                type="number"
                min={30}
                max={maxTemp}
                step={1}
                value={s.tempLimitC}
                disabled={disabled}
                onChange={(e) => num('tempLimitC', e.target.value, 30, maxTemp)}
              />
              °C
            </label>
            <label className="stress-field" title="a shaft that moves this far from where it started means the fixture let go" hidden={free}>
              its shaft moves
              <input
                type="number"
                min={5}
                max={720}
                step={5}
                value={s.slipDeg}
                disabled={disabled}
                onChange={(e) => num('slipDeg', e.target.value, 5, 720)}
              />
              °
            </label>
          </div>
        </div>

        <div className="thermal-field-group">
          <span className="thermal-group-title">csv</span>
          <div className="bench-fields">
            <label className="stress-field" title="rows per second per motor">
              sample rows
              <input
                type="number"
                min={0.2}
                max={10}
                step={1}
                value={s.logHz}
                disabled={disabled}
                onChange={(e) => num('logHz', e.target.value, 0.2, 10)}
              />
              Hz
            </label>
            <label className="stress-field" title="a new file is started once the current one reaches this size">
              split at
              <input
                type="number"
                min={1}
                max={2000}
                step={10}
                value={s.logPartMb}
                disabled={disabled}
                onChange={(e) => num('logPartMb', e.target.value, 1, 2000)}
              />
              MB
            </label>
          </div>
        </div>
      </div>
    </section>
  )
}

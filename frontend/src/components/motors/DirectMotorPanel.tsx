// Hidden-by-default raw motor control for bring-up/diagnosis: an expandable
// at the bottom of the Motor Control panel with one slider per MOTOR
// (radians, motor space — bypasses the joint mapping entirely). Arming it
// pauses the feedback loop's writes server-side and suspends joint targets;
// per-move distance is clamped by the backend. Latched hardware errors
// (the "motor answers reads but won't turn" class) are shown per motor.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type {
  DirectMotorInfo,
  DirectMotorSnapshot,
  MotorModelInfo,
} from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'

const SLIDER_HALF_RANGE_RAD = 0.5 // slider span around the anchor position
const SEND_THROTTLE_MS = 80
// Samples kept for the current readout. Present current is the instantaneous
// phase current of a PWM-driven coil, so one sample at the bench rate lands
// anywhere on the waveform: read raw it looks like noise. A second of them
// shows what the motor is actually drawing, and the peak beside it shows the
// transient a cap does not catch.
const CURRENT_WINDOW = 20
/** How bench playback paces itself, for every motor at once.
 *
 * The same three controls as a motor-waypoint replay, in the same order and
 * with the same defaults: this is the same mechanism under a different
 * panel, so an operator who has set one should recognise the other.
 *
 * Bench-wide rather than per motor: one thread drives the shared bus and
 * arrival is a whole-chain condition, so two motors pacing themselves
 * differently would only mean one waiting on the other.
 */
function BenchPacing() {
  const [steps, setSteps] = useState('')
  const [period, setPeriod] = useState('')
  const [settle, setSettle] = useState('')
  const [saved, setSaved] = useState(false)
  const setError = useAppStore((s) => s.setError)

  const apply = () => {
    const n = Math.min(200, Math.max(1, parseInt(steps, 10) || 1))
    const ms = Math.min(5000, Math.max(20, parseInt(period, 10) || 100))
    const raw = settle.trim()
    const parsed = parseInt(raw, 10)
    const cap =
      raw === '' || !Number.isFinite(parsed)
        ? null
        : Math.min(60000, Math.max(1, parsed))
    void api
      .motorsDirectPacing(n, cap, ms)
      .then(() => {
        setSaved(true)
        setError(null)
        window.setTimeout(() => setSaved(false), 1500)
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        marginBottom: 6,
        color: 'var(--dim)',
      }}
    >
      <span>playback</span>
      <input
        type="number"
        min={1}
        max={200}
        placeholder="1"
        title={
          'commands per segment \u2014 1 moves directly from each recorded ' +
          'point to the next, and the motor\u2019s own controller does the ' +
          'travelling'
        }
        value={steps}
        onChange={(e) => setSteps(e.target.value)}
        style={{ width: 48 }}
      />
      <label
        title={
          'ms between commands, which is also the rest at each point once ' +
          'every motor has arrived. At 1 command per segment that rest is ' +
          'all it is; above 1 it also spaces the steps spanning a segment. ' +
          'A dwell longer than the settle cap outlasts it, so the cap only ' +
          'bites once this is short enough to notice.'
        }
      >
        <input
          type="number"
          min={20}
          max={5000}
          step={10}
          placeholder="100"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          style={{ width: 56 }}
        />
        ms
      </label>
      <label
        title={
          'max settle \u2014 ms to wait at each point before sending the ' +
          'next command even if a motor has not reported arriving. Empty ' +
          'waits for every motor; set it when one motor cannot reach its ' +
          'point and should not hold up the rest.'
        }
      >
        settle
        <input
          type="number"
          min={1}
          max={60000}
          step={50}
          placeholder="wait"
          value={settle}
          onChange={(e) => setSettle(e.target.value)}
          style={{ width: 56 }}
        />
        ms
      </label>
      <button className="btn btn-secondary" onClick={apply}>
        {saved ? 'set' : 'apply'}
      </button>
    </div>
  )
}

export function DirectMotorPanel({
  torqueOn,
  locked,
  forceOpen = false,
  bench = false,
}: {
  torqueOn: boolean
  locked: boolean
  // Open by default and stay expanded: the hand isn't calibrated, so this
  // is the only way to move a motor until Setup → Calibrate runs.
  forceOpen?: boolean
  // Bench mode (bare motors): an absolute angle over the whole travel,
  // committed on Go, with the load readings a stall test needs. A hand gets
  // the nudge-from-here slider instead, which is safer next to tendons.
  bench?: boolean
}) {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const [open, setOpen] = useState(forceOpen)
  const [snapshot, setSnapshot] = useState<DirectMotorSnapshot | null>(null)
  const [models, setModels] = useState<MotorModelInfo[]>([])
  const [values, setValues] = useState<Record<number, number>>({})
  const [busy, setBusy] = useState(false)
  const armed = control?.direct_motor_mode ?? false
  const span = snapshot?.span_rad ?? null

  useEffect(() => {
    if (!bench) return
    void api
      .motorsModels()
      .then((r) => setModels(r.models))
      .catch(() => setModels([]))
  }, [bench])

  const fail = (error: unknown) =>
    setError(String((error as Error).message ?? error))

  const refresh = async () => {
    try {
      const snap = await api.motorsDirect()
      setSnapshot(snap)
      const anchors: Record<number, number> = {}
      for (const motor of snap.motors) anchors[motor.id] = motor.position
      setValues(anchors)
    } catch (error) {
      fail(error)
    }
  }

  useEffect(() => {
    if (open) void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // handInfo (and so forceOpen) can resolve after this panel already
  // mounted closed; re-open the moment calibration state says it's needed.
  // Does not fight a manual collapse — only fires when forceOpen flips on.
  useEffect(() => {
    if (forceOpen) setOpen(true)
  }, [forceOpen])

  // Best-effort disarm when the section closes or the panel unmounts.
  useEffect(() => {
    if (!open && armed) void api.motorsDirectMode(false).catch(() => undefined)
    return () => {
      if (armed) void api.motorsDirectMode(false).catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const setArmed = async (enabled: boolean) => {
    setBusy(true)
    try {
      await api.motorsDirectMode(enabled)
      if (enabled) await refresh() // re-anchor sliders at the armed pose
      setError(null)
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      style={{ marginTop: 10, fontSize: 10 }}
    >
      <summary
        style={{
          cursor: 'pointer',
          color: forceOpen ? 'var(--warn)' : 'var(--dimmer)',
          fontWeight: forceOpen ? 600 : undefined,
        }}
      >
        {forceOpen
          ? 'Direct motor control — use this, the hand is not calibrated'
          : 'Direct motor control (advanced)'}
      </summary>
      <div style={{ padding: '6px 0 0 0' }}>
        {bench && <BenchPacing />}
        <div style={{ color: 'var(--warn)', marginBottom: 6 }}>
          {bench ? (
            <>
              Find each motor&apos;s range first: the servo goes limp, you turn
              it to each end by hand, and the two limits you set become the
              slider. Travel is counted as you turn, so going past the
              encoder&apos;s boundary still adds up and the direction you went
              is what the slider follows. After that the slider drives the
              motor as it moves, and a typed angle goes there on Go. Watch the
              current: pinned high against a target it has not reached is the
              load this motor cannot move.
            </>
          ) : (
            <>
              Raw motor-space positions in radians — bypasses the joint mapping
              and ROM limits. Arming pauses the feedback loop and suspends joint
              sliders. Moves are capped at{' '}
              {(snapshot?.max_step_rad ?? 0.8).toFixed(1)} rad per command.
            </>
          )}
        </div>
        {bench && models.length > 0 && snapshot && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 6,
                        alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ color: 'var(--dimmer)' }}>declare every motor as</span>
            <select
              defaultValue=""
              disabled={busy}
              title="a chain is usually one model; declare it once"
              onChange={(e) => {
                const key = e.target.value
                e.target.value = ''
                if (!key) return
                setBusy(true)
                Promise.all(
                  snapshot.motors.map((m) =>
                    api.motorsDirectDeclare(m.id, key, m.nickname ?? null),
                  ),
                )
                  .then(() => refresh())
                  .catch(fail)
                  .finally(() => setBusy(false))
              }}
            >
              <option value="">choose a model…</option>
              {models
                .filter((m) => m.key !== 'unknown')
                .map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.label}
                  </option>
                ))}
            </select>
            <span style={{ color: 'var(--dimmer)' }}>
              ({snapshot.motors.length} motors)
            </span>
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
          {!armed ? (
            <button
              className="btn btn-danger"
              disabled={busy || locked || !torqueOn || !snapshot}
              title={
                !torqueOn ? 'enable torque first' : locked ? 'control is owned' : undefined
              }
              onClick={() => void setArmed(true)}
            >
              Arm direct control
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={busy}
              onClick={() => void setArmed(false)}
            >
              Disarm
            </button>
          )}
          <button
            className="btn btn-secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            Refresh
          </button>
        </div>
        {snapshot?.motors.map((motor) =>
          bench ? (
            <BenchMotorRow
              key={motor.id}
              motor={motor}
              span={span}
              disabled={!armed || locked || !torqueOn}
              onError={fail}
              onChanged={refresh}
              models={models}
            />
          ) : (
            <MotorRow
              key={motor.id}
              motor={motor}
              value={values[motor.id] ?? motor.position}
              disabled={!armed || locked || !torqueOn}
              onSlide={(v) => setValues((prev) => ({ ...prev, [motor.id]: v }))}
              onError={fail}
            />
          ),
        )}
      </div>
    </details>
  )
}

function MotorRow({
  motor,
  value,
  disabled,
  onSlide,
  onError,
}: {
  motor: DirectMotorInfo
  value: number
  disabled: boolean
  onSlide: (value: number) => void
  onError: (error: unknown) => void
}) {
  const lastSent = useRef(0)
  const pending = useRef<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Throttled sender: at most one POST per SEND_THROTTLE_MS, always
  // flushing the final value.
  const send = (v: number) => {
    const flush = (val: number) => {
      lastSent.current = performance.now()
      void api.motorsDirectPosition(motor.id, val).catch(onError)
    }
    const elapsed = performance.now() - lastSent.current
    if (elapsed >= SEND_THROTTLE_MS) {
      flush(v)
    } else {
      pending.current = v
      if (timer.current === null) {
        timer.current = setTimeout(() => {
          timer.current = null
          if (pending.current !== null) {
            const val = pending.current
            pending.current = null
            flush(val)
          }
        }, SEND_THROTTLE_MS - elapsed)
      }
    }
  }

  const lo = motor.position - SLIDER_HALF_RANGE_RAD
  const hi = motor.position + SLIDER_HALF_RANGE_RAD
  const flags = motor.hw_error_flags
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '2px 0',
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <span style={{ width: 84, textAlign: 'right', color: 'var(--text)' }}>
        M{motor.id} <span style={{ color: 'var(--dimmer)' }}>{motor.joint}</span>
      </span>
      <input
        type="range"
        min={lo}
        max={hi}
        step={0.005}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const v = parseFloat(e.target.value)
          onSlide(v)
          send(v)
        }}
        style={{ flex: 1, height: 3, accentColor: 'var(--err)', cursor: 'pointer' }}
      />
      <span style={{ width: 56, fontWeight: 600, color: 'var(--text)', textAlign: 'right' }}>
        {value.toFixed(3)}
      </span>
      {flags && flags.length > 0 ? (
        <span
          title={`Latched hardware error 0x${(motor.hw_error ?? 0)
            .toString(16)
            .padStart(2, '0')} — the motor refuses to energize until rebooted
(power-cycle or reconnect). electrical_shock/input_voltage point at the
motor's power wiring.`}
          style={{ width: 100, color: 'var(--err)', fontSize: 9, cursor: 'help' }}
        >
          ⚠ {flags.join(', ')}
        </span>
      ) : (
        <span style={{ width: 100, color: 'var(--dimmer)', fontSize: 9 }}>
          {motor.hw_error === null ? '' : 'ok'}
        </span>
      )}
    </div>
  )
}


// A single-turn magnetic encoder reports an angle, not a turn count, so
// turning the shaft past its boundary by hand makes the reading jump a whole
// turn. Accumulating the unwrapped travel is what lets a range found by hand
// mean something: it gives the real distance between the two ends and, from
// its sign, which way the operator went.
function unwrapStep(prev: number, next: number, turn: number | null): number {
  const delta = next - prev
  // A multi-turn family counts revolutions, so its reading is already
  // continuous and there is nothing to undo.
  if (turn === null) return delta
  if (delta > turn / 2) return delta - turn
  if (delta < -turn / 2) return delta + turn
  return delta
}

type RangeFind =
  | { phase: 'idle' }
  | { phase: 'first' }
  | { phase: 'second'; first: number; travel: number; last: number }

// Recording is simpler than finding a range: each press captures where the
// motor is, and a raw reading is already a valid target. Only measuring the
// distance between two ends needed the unwrapping.
type Recording = { active: boolean; points: number[] }

// One motor on the bench. Until a range is found the only useful action is
// finding one: a raw angle over the servo's whole turn means nothing when the
// motor is bolted to something that stops well short of it. Once found, the
// slider spans exactly that travel and drives the motor as it moves.
function BenchMotorRow({
  motor,
  span,
  disabled,
  onError,
  onChanged,
  models,
}: {
  motor: DirectMotorInfo
  // The bench-wide declared travel, when every bus agrees on one. This motor's
  // own span wins over it: two families disagree, and a slider drawn over the
  // other bus's travel would drive this motor into a stop.
  span: [number, number] | null
  disabled: boolean
  onError: (error: unknown) => void
  // Ranges, points and play state live on the server, so anything that writes
  // them has to pull the snapshot again or the row keeps showing the old one.
  onChanged: () => Promise<void> | void
  models: MotorModelInfo[]
}) {
  const travel = motor.span_rad ?? span
  const turn = travel ? Math.abs(travel[1] - travel[0]) : null
  const range = motor.range_rad ?? null

  // Live position and current at the bench rate, so a stall is visible while
  // it happens rather than on the next Refresh.
  const [live, setLive] = useState<{
    pos: number | null
    mA: number | null
    tempC: number | null
  }>({ pos: null, mA: null, tempC: null })
  const [find, setFind] = useState<RangeFind>({ phase: 'idle' })
  const [rec, setRec] = useState<Recording>({ active: false, points: [] })
  const [target, setTarget] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const findRef = useRef(find)
  findRef.current = find
  const currentWindow = useRef<number[]>([])
  const [currentStats, setCurrentStats] =
    useState<{ mean: number; peak: number } | null>(null)

  useStreamFrame((frames) => {
    const pos = frames.motors.positions?.[String(motor.id)]
    const mA = frames.motors.currents?.[String(motor.id)]
    const tempC = frames.motors.temps?.[String(motor.id)]
    if (mA !== undefined) {
      const w = currentWindow.current
      w.push(mA)
      if (w.length > CURRENT_WINDOW) w.shift()
      const mean = w.reduce((a, b) => a + b, 0) / w.length
      const peak = Math.max(...w)
      setCurrentStats((prev) =>
        prev && Math.round(prev.mean) === Math.round(mean) &&
        Math.round(prev.peak) === Math.round(peak)
          ? prev
          : { mean, peak },
      )
    }
    if (pos !== undefined || mA !== undefined || tempC !== undefined) {
      setLive((prev) =>
        prev.pos === (pos ?? null) &&
        prev.mA === (mA ?? null) &&
        prev.tempC === (tempC ?? null)
          ? prev
          : { pos: pos ?? null, mA: mA ?? null, tempC: tempC ?? null },
      )
    }
    // Accumulate travel between the two limits, so a turn past the encoder
    // boundary still adds up and its sign still says which way we went.
    const state = findRef.current
    if (state.phase === 'second' && pos !== undefined) {
      const step = unwrapStep(state.last, pos, turn)
      if (step !== 0) {
        setFind({ ...state, travel: state.travel + step, last: pos })
      }
    }
  })

  const position = live.pos ?? motor.position
  const currentMa = live.mA ?? motor.current_ma ?? null
  const tempC = live.tempC ?? motor.temp_c ?? null

  // Degrees within the found range: 0 at the end the operator set first.
  const lo = range ? Math.min(range[0], range[1]) : (span?.[0] ?? 0)
  const hi = range ? Math.max(range[0], range[1]) : (span?.[1] ?? 0)
  const spanDeg = ((hi - lo) * 180) / Math.PI
  const posDeg = ((position - lo) * 180) / Math.PI
  const parsed = Number.parseFloat(target)
  const valid = Number.isFinite(parsed) && parsed >= 0 && parsed <= spanDeg

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      await onChanged()
    } catch (e) {
      onError(e)
    } finally {
      setBusy(false)
    }
  }

  const startFind = () =>
    void call(async () => {
      await api.motorsDirectRange(motor.id, null, null)
      await api.motorsDirectTorque(motor.id, false)
      setFind({ phase: 'first' })
    })

  const setFirst = () =>
    setFind({ phase: 'second', first: position, travel: 0, last: position })

  const setSecond = () =>
    void call(async () => {
      const state = findRef.current
      if (state.phase !== 'second') return
      const second = state.first + state.travel
      await api.motorsDirectRange(
        motor.id,
        Math.min(state.first, second),
        Math.max(state.first, second),
      )
      await api.motorsDirectTorque(motor.id, true)
      setFind({ phase: 'idle' })
      setTarget('')
    })

  const cancelFind = () =>
    void call(async () => {
      await api.motorsDirectTorque(motor.id, true)
      setFind({ phase: 'idle' })
    })

  const clearRange = () =>
    void call(async () => {
      await api.motorsDirectRange(motor.id, null, null)
      setTarget('')
    })

  // Slide-to-move: the range is known and bounded, so there is no reason to
  // make the operator press Go for every nudge.
  const sendDeg = (deg: number) => {
    const rad = lo + (deg * Math.PI) / 180
    void api.motorsDirectPosition(motor.id, rad).catch(onError)
  }

  const points = motor.points ?? null
  const playing = motor.playing ?? false

  const startRecord = () =>
    void call(async () => {
      await api.motorsDirectPlay(motor.id, false)
      await api.motorsDirectPoints(motor.id, null)
      await api.motorsDirectTorque(motor.id, false)
      setRec({ active: true, points: [] })
    })

  const addPoint = () =>
    setRec((prev) => ({ ...prev, points: [...prev.points, position] }))

  const finishRecord = () =>
    void call(async () => {
      const captured = rec.points
      // Store first, clear second. Clearing up front threw the recording away
      // whenever the store was refused, leaving nothing on screen and no way
      // back to the points the operator had just captured by hand.
      if (captured.length > 0) {
        await api.motorsDirectPoints(motor.id, captured)
      }
      await api.motorsDirectTorque(motor.id, true)
      setRec({ active: false, points: [] })
    })

  const cancelRecord = () =>
    void call(async () => {
      setRec({ active: false, points: [] })
      await api.motorsDirectTorque(motor.id, true)
    })

  const addHere = () =>
    void call(() =>
      api.motorsDirectPoints(motor.id, [...(points ?? []), position]),
    )

  const flags = motor.hw_error_flags
  const finding = find.phase !== 'idle'

  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '6px 0' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ width: 92, color: 'var(--text)' }} title={`motor ID ${motor.id}`}>
          M{motor.id}
          {motor.nickname ? (
            <span style={{ color: 'var(--dim)' }}> {motor.nickname}</span>
          ) : null}
        </span>

        {rec.active ? (
          <>
            <span style={{ color: 'var(--warn)', flex: 1, minWidth: 200 }}>
              Limp — move it to a position and record it. {rec.points.length}{' '}
              recorded.{' '}
              {rec.points.length === 1
                ? 'One point is a place to hold.'
                : rec.points.length > 1
                  ? 'It will cycle between them.'
                  : ''}
            </span>
            <button className="btn btn-primary" disabled={busy} onClick={addPoint}>
              Record point
            </button>
            <button
              className="btn btn-primary"
              disabled={busy || rec.points.length === 0}
              onClick={finishRecord}
            >
              Done
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={cancelRecord}>
              Cancel
            </button>
          </>
        ) : finding ? (
          <>
            <span style={{ color: 'var(--warn)', flex: 1, minWidth: 200 }}>
              {find.phase === 'first'
                ? 'Limp — turn it to one end of its travel, then set the first limit.'
                : `Now turn it to the other end. ${Math.abs(
                    (find.travel * 180) / Math.PI,
                  ).toFixed(1)}° travelled ${find.travel >= 0 ? 'forward' : 'back'}.`}
            </span>
            <button
              className="btn btn-primary"
              disabled={busy}
              onClick={find.phase === 'first' ? setFirst : setSecond}
            >
              {find.phase === 'first' ? 'Set first limit' : 'Set second limit'}
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={cancelFind}>
              Cancel
            </button>
          </>
        ) : !range ? (
          <>
            <span style={{ color: 'var(--dim)', flex: 1, minWidth: 200 }}>
              No range found — the servo&apos;s full turn is rarely what this
              motor can actually travel.
            </span>
            <button className="btn btn-primary" disabled={busy || disabled} onClick={startFind}>
              Find range
            </button>
          </>
        ) : (
          <>
            <input
              type="range"
              min={0}
              max={spanDeg}
              step={0.5}
              value={valid ? parsed : Math.max(0, Math.min(spanDeg, posDeg))}
              disabled={disabled}
              onChange={(e) => {
                setTarget(e.target.value)
                sendDeg(Number.parseFloat(e.target.value))
              }}
              style={{ flex: 1, minWidth: 140 }}
            />
            <input
              type="number"
              min={0}
              max={Math.round(spanDeg * 10) / 10}
              step={0.5}
              value={target}
              disabled={disabled}
              placeholder={posDeg.toFixed(1)}
              onChange={(e) => setTarget(e.target.value)}
              style={{ width: 66 }}
            />
            <span style={{ color: 'var(--dimmer)' }}>
              / {spanDeg.toFixed(1)}°
            </span>
            <button
              className="btn btn-primary"
              disabled={disabled || !valid}
              onClick={() => sendDeg(parsed)}
            >
              Go
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={clearRange}>
              Clear range
            </button>
          </>
        )}
      </div>

      {!rec.active && !finding && (
        <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          {points && points.length > 0 ? (
            <>
              <span style={{ color: 'var(--dim)' }}>
                {points.length === 1
                  ? '1 point recorded — holds there'
                  : `${points.length} points recorded — cycles between them`}
              </span>
              <button
                className="btn btn-secondary"
                disabled={busy || playing}
                title={playing
                  ? 'stop the sequence before adding to it'
                  : 'append wherever the motor is now — drive it there with ' +
                    'the slider or Go first'}
                onClick={addHere}
              >
                + here
              </button>
              <button
                className={playing ? 'btn btn-danger' : 'btn btn-primary'}
                disabled={busy || disabled}
                title={playing ? 'stop the sequence' : 'run the recorded points'}
                onClick={() =>
                  void call(() => api.motorsDirectPlay(motor.id, !playing))
                }
              >
                {playing ? 'Stop' : 'Play'}
              </button>
              <button
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => void call(() => api.motorsDirectPoints(motor.id, null))}
              >
                Clear points
              </button>
            </>
          ) : (
            <>
              <button
                className="btn btn-secondary"
                disabled={busy || disabled}
                title={
                  'append wherever the motor is now — drive it there with ' +
                  'the slider or Go first'
                }
                onClick={addHere}
              >
                + here
              </button>
              <button
                className="btn btn-secondary"
                disabled={busy || disabled}
                title="go limp, then capture positions by hand"
                onClick={startRecord}
              >
                Record by hand
              </button>
            </>
          )}
        </div>
      )}

      {!rec.active && !finding && (
        <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center',
                      flexWrap: 'wrap', fontSize: 10 }}>
          <span style={{ color: 'var(--dimmer)' }}>is a</span>
          <select
            value={motor.model?.key ?? 'unknown'}
            disabled={busy}
            title={motor.model?.source ?? 'declare what is plugged in here'}
            onChange={(e) =>
              void call(() =>
                api.motorsDirectDeclare(motor.id, e.target.value,
                                        motor.nickname ?? null),
              )
            }
          >
            {models.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="nickname"
            defaultValue={motor.nickname ?? ''}
            disabled={busy}
            title="a name for this motor on the bench"
            onBlur={(e) =>
              void call(() =>
                api.motorsDirectDeclare(motor.id,
                                        motor.model?.key ?? null,
                                        e.target.value),
              )
            }
            style={{ width: 110 }}
          />
          {motor.reported_model_number != null && (
            <span style={{ color: 'var(--dimmer)' }}>
              reports {motor.reported_model_number}
            </span>
          )}
          {motor.mismatch && (
            <span style={{ color: 'var(--err)' }}>
              ⚠ the servo reports {motor.identified?.label ?? 'another model'} —
              one of these is wrong
            </span>
          )}
          {!motor.model?.has_current_control && (
            <span style={{ color: 'var(--warn)' }}>
              no current ceiling written
            </span>
          )}
        </div>
      )}

      <div
        style={{
          display: 'flex',
          gap: 12,
          marginTop: 4,
          flexWrap: 'wrap',
          color: 'var(--dim)',
        }}
      >
        <span>
          at{' '}
          {range
            ? `${posDeg.toFixed(1)}° of ${spanDeg.toFixed(1)}°`
            : `${((position * 180) / Math.PI).toFixed(1)}° raw`}
        </span>
        {currentStats != null ? (
          <span title={
            'mean over the last second, then the peak in that window. ' +
            'Present current is the instantaneous phase current of a PWM ' +
            'coil, so a single sample is not meaningful. A cap holds the ' +
            'mean; the peak rides above it during a move, which is the ' +
            'current loop catching up rather than the cap failing.'
          }>
            {currentStats.mean.toFixed(0)} mA
            <span style={{ color: 'var(--dimmer)' }}>
              {' '}peak {currentStats.peak.toFixed(0)}
            </span>
          </span>
        ) : currentMa != null ? (
          <span>{currentMa.toFixed(0)} mA</span>
        ) : null}
        {tempC != null && <span>{tempC.toFixed(0)} °C</span>}
        {flags && flags.length > 0 && (
          <span style={{ color: 'var(--err)' }}>{flags.join(' + ')}</span>
        )}
      </div>
    </div>
  )
}

// One motor: live shaft readout, jog buttons, and the two captured endpoints.
//
// Readouts are written straight into the DOM from the 10 Hz motors.state
// stream (no re-render per sample). Capture takes the live position — the
// operator turned the spool there with torque off, or jogged it there with
// torque on — so a range is always something the bench has actually been at.

import { useRef, useState } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'
import { useOperationActive, useOperationStore } from '../state/operationStore'
import { type BenchMotor, useBenchStore } from './benchStore'
import { CycleFields } from './CycleFields'
import { formatDeg, formatMa, useMotorLive } from './useMotorLive'

// Below the backend's 0.8 rad per-move cap, so every jog is one accepted write.
const JOG_STEPS_DEG = [2, 10, 30]
const JOG_REPEAT_MS = 180
const JOG_REPEAT_AFTER_MS = 400
const DEG = Math.PI / 180

export function MotorCard({ motor, connected }: { motor: BenchMotor; connected: boolean }) {
  const setup = useBenchStore((s) => s.setup[motor.id])
  const patchMotor = useBenchStore((s) => s.patchMotor)
  const control = useAppStore((s) => s.control)
  const held = control?.held_motors?.includes(motor.id) ?? false
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const ours = useOperationStore(
    (s) => s.operation?.kind === 'motor_cycle' && opActive,
  )
  const [step, setStep] = useState(JOG_STEPS_DEG[1])
  const [jogging, setJogging] = useState(false)
  const [holdBusy, setHoldBusy] = useState(false)

  const posRef = useRef<HTMLSpanElement>(null)
  const curRef = useRef<HTMLSpanElement>(null)
  const velRef = useRef<HTMLSpanElement>(null)
  const tempRef = useRef<HTMLSpanElement>(null)
  const faultRef = useRef<HTMLSpanElement>(null)
  const livePos = useRef<number | null>(null)
  const repeat = useRef<{ timer: number | null; interval: number | null }>({
    timer: null,
    interval: null,
  })

  const id = String(motor.id)
  useMotorLive((frames) => {
    const pos = frames.motors.positions[id]
    livePos.current = pos ?? null
    if (posRef.current) posRef.current.textContent = formatDeg(pos)
    if (curRef.current) curRef.current.textContent = formatMa(frames.motors.currents[id])
    if (velRef.current) {
      const v = frames.motors.velocities[id]
      velRef.current.textContent = v === undefined ? '—' : `${v.toFixed(0)}°/s`
    }
    if (tempRef.current) {
      const t = frames.motors.temps[id]
      const max = frames.motors.maxTempC ?? 70
      tempRef.current.textContent = t === undefined ? '—' : `${t.toFixed(0)} °C`
      tempRef.current.className =
        t === undefined ? '' : t >= max * 0.9 ? 'err' : t >= max * 0.7 ? 'warn' : 'ok'
    }
    if (faultRef.current) {
      const entry = frames.motors.faults?.motors[id]
      const hw = entry?.hw_error
      if (hw) {
        faultRef.current.textContent = hw.headline
        faultRef.current.title = hw.advice
        faultRef.current.className = 'bench-fault err'
      } else if (entry && entry.errors > 0) {
        faultRef.current.textContent = `${entry.errors} bus errors`
        faultRef.current.title = entry.last_error ?? ''
        faultRef.current.className = 'bench-fault warn'
      } else {
        faultRef.current.textContent = ''
        faultRef.current.className = 'bench-fault'
      }
    }
  })

  const manual = control?.control_source === 'manual'
  const canJog = connected && held && manual && !opActive
  const canHold = connected && manual && !opActive && !holdBusy

  const toggleHold = async () => {
    setHoldBusy(true)
    try {
      await api.motorTorque(motor.id, !held)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setHoldBusy(false)
    }
  }

  const jogOnce = async (direction: 1 | -1) => {
    try {
      let positionDeg = livePos.current
      if (positionDeg === null) {
        const snapshot = await api.motorsDirect()
        const entry = snapshot.motors.find((m) => m.id === motor.id)
        if (!entry) return
        positionDeg = entry.position / DEG
      }
      if (!useAppStore.getState().control?.direct_motor_mode) {
        await api.motorsDirectMode(true)
      }
      const target = (positionDeg + direction * step) * DEG
      await api.motorsDirectPosition(motor.id, target)
      // Optimistic: the next stream sample confirms, and a held button keeps
      // stepping from where the last write asked for.
      livePos.current = positionDeg + direction * step
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
      stopRepeat()
    }
  }

  const stopRepeat = () => {
    const r = repeat.current
    if (r.timer !== null) window.clearTimeout(r.timer)
    if (r.interval !== null) window.clearInterval(r.interval)
    r.timer = null
    r.interval = null
    setJogging(false)
  }

  const startRepeat = (direction: 1 | -1) => {
    if (!canJog) return
    setJogging(true)
    void jogOnce(direction)
    repeat.current.timer = window.setTimeout(() => {
      repeat.current.interval = window.setInterval(
        () => void jogOnce(direction),
        JOG_REPEAT_MS,
      )
    }, JOG_REPEAT_AFTER_MS)
  }

  const capture = (which: 'a' | 'b') => {
    const value = livePos.current
    if (value === null) {
      setError(`motor ${motor.number}: no live position yet`)
      return
    }
    patchMotor(motor.id, { [which]: Math.round(value * 10) / 10 })
  }

  const edit = (which: 'a' | 'b', text: string) => {
    const value = parseFloat(text)
    patchMotor(motor.id, { [which]: Number.isFinite(value) ? value : null })
  }

  const a = setup?.a ?? null
  const b = setup?.b ?? null
  const span = a !== null && b !== null ? Math.abs(b - a) : null

  return (
    <section className={`panel bench-motor ${setup?.included ? '' : 'excluded'}`}>
      <div className="bench-motor-head">
        <label className="bench-include" title="include this motor in the next run">
          <input
            type="checkbox"
            checked={setup?.included ?? true}
            onChange={(e) => patchMotor(motor.id, { included: e.target.checked })}
          />
          <h2>Motor {motor.number}</h2>
        </label>
        <span className="bench-joint" title="the servo's id on the bus">ID {motor.id}</span>
        <span ref={faultRef} className="bench-fault" />
        <button
          className={`btn bench-hold-one ${held ? 'btn-danger' : 'btn-info'}`}
          disabled={!canHold}
          title={
            !connected
              ? 'no motor bus'
              : opActive
                ? 'a run is in progress'
                : held
                  ? 'release: this motor turns freely'
                  : 'hold: torque on, this motor pins where it is (others unchanged)'
          }
          onClick={() => void toggleHold()}
        >
          {held ? '◼ Release' : '⏻ Hold'}
        </button>
      </div>

      <div className="bench-readout">
        <span ref={posRef} className="bench-pos">—</span>
        <div className="bench-readout-side">
          <span>
            <span ref={curRef}>—</span>
            <small>current</small>
          </span>
          <span>
            <span ref={velRef}>—</span>
            <small>speed</small>
          </span>
          <span>
            <span ref={tempRef}>—</span>
            <small>temp</small>
          </span>
        </div>
      </div>

      <div className="bench-jog">
        <button
          className="btn btn-secondary bench-jog-btn"
          disabled={!canJog}
          title={canJog ? `turn ${step}° back (hold to repeat)` : 'hold this motor first'}
          onPointerDown={() => startRepeat(-1)}
          onPointerUp={stopRepeat}
          onPointerLeave={stopRepeat}
          onPointerCancel={stopRepeat}
        >
          −
        </button>
        <span className="bench-jog-steps">
          {JOG_STEPS_DEG.map((value) => (
            <button
              key={value}
              className={`btn ${step === value ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setStep(value)}
            >
              {value}°
            </button>
          ))}
        </span>
        <button
          className="btn btn-secondary bench-jog-btn"
          disabled={!canJog}
          title={canJog ? `turn ${step}° forward (hold to repeat)` : 'hold this motor first'}
          onPointerDown={() => startRepeat(1)}
          onPointerUp={stopRepeat}
          onPointerLeave={stopRepeat}
          onPointerCancel={stopRepeat}
        >
          +
        </button>
        {jogging && <span className="bench-jogging">jogging…</span>}
      </div>

      <div className="bench-endpoints">
        {(['a', 'b'] as const).map((which) => (
          <div key={which} className="bench-endpoint">
            <span className="bench-endpoint-name">{which.toUpperCase()}</span>
            <input
              type="number"
              step={0.1}
              value={setup?.[which] ?? ''}
              placeholder="—"
              onChange={(e) => edit(which, e.target.value)}
            />
            <span className="bench-unit">°</span>
            <button
              className="btn btn-primary"
              disabled={!connected || opActive}
              title={`capture the live position as ${which.toUpperCase()}`}
              onClick={() => capture(which)}
            >
              Set {which.toUpperCase()}
            </button>
          </div>
        ))}
        <div className="bench-span">
          <span>{span === null ? 'set both ends' : `${span.toFixed(1)}° travel`}</span>
        </div>
      </div>

      {setup && (
        <CycleFields
          value={setup}
          onChange={(patch) => patchMotor(motor.id, patch)}
          disabled={ours}
          name={`motor-${motor.id}`}
        />
      )}
    </section>
  )
}

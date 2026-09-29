// Hidden-by-default raw motor control for bring-up/diagnosis: an expandable
// at the bottom of the Motor Control panel with one slider per MOTOR
// (radians, motor space — bypasses the joint mapping entirely). Arming it
// pauses the feedback loop's writes server-side and suspends joint targets;
// per-move distance is clamped by the backend. Latched hardware errors
// (the "motor answers reads but won't turn" class) are shown per motor.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { DirectMotorInfo, DirectMotorSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'

const SLIDER_HALF_RANGE_RAD = 0.5 // slider span around the anchor position
const SEND_THROTTLE_MS = 80
// A commanded angle this close to the reading counts as arrived. Wider than the
// servo's own resolution so a motor holding under load does not read as missing.
const ARRIVED_DEG = 2.0

// Absolute angle over the motor's travel: 0 at one end, 360 at the other. The
// servo's own frame is used rather than an offset from wherever the motor
// happened to sit, so every value on the dial is reachable. An offset zero
// would put half the dial outside the travel on a motor that started
// mid-range, and an unreachable command clamps against a hard stop.
function radToDeg(rad: number, span: [number, number]): number {
  const [lo, hi] = span
  return ((rad - lo) / (hi - lo)) * 360
}

function degToRad(deg: number, span: [number, number]): number {
  const [lo, hi] = span
  return lo + (deg / 360) * (hi - lo)
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
  const [values, setValues] = useState<Record<number, number>>({})
  const [busy, setBusy] = useState(false)
  const armed = control?.direct_motor_mode ?? false
  const span = snapshot?.span_rad ?? null

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
        <div style={{ color: 'var(--warn)', marginBottom: 6 }}>
          {bench && !span ? (
            <>
              This motor family has no single-turn limit, so there is no fixed
              travel to lay a 0 to 360° dial over. Nudging from the current
              position is what is offered instead.
            </>
          ) : bench ? (
            <>
              Absolute angle over each motor&apos;s full travel, 0 to 360°.
              Commit a target with <strong>Go</strong> and the servo holds it
              under its current limit. If it stops short, the error stays open
              and the current sits at the ceiling — that is the load it cannot
              move. Raise the ceiling in the Motors tab to push further.
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
          bench && span ? (
            <BenchMotorRow
              key={motor.id}
              motor={motor}
              span={span}
              disabled={!armed || locked || !torqueOn}
              onError={fail}
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

// One motor on the bench: command an absolute angle, watch whether it gets
// there. The stall is the point — a missed target with the current pinned at
// the ceiling is the load this motor cannot move.
function BenchMotorRow({
  motor,
  span,
  disabled,
  onError,
}: {
  motor: DirectMotorInfo
  span: [number, number]
  disabled: boolean
  onError: (error: unknown) => void
}) {
  const actualDeg = radToDeg(motor.position, span)
  const [target, setTarget] = useState<string>(actualDeg.toFixed(1))
  const [commanded, setCommanded] = useState<number | null>(null)
  // A reference the operator sets by hand, so "how far did it turn" is
  // readable without doing arithmetic. Display only: commands stay absolute,
  // because an offset zero cannot promise the dial is reachable.
  const [mark, setMark] = useState<number | null>(null)

  const parsed = Number.parseFloat(target)
  const valid = Number.isFinite(parsed) && parsed >= 0 && parsed <= 360
  const error = commanded === null ? null : commanded - actualDeg
  const arrived = error !== null && Math.abs(error) <= ARRIVED_DEG

  const go = () => {
    if (!valid) return
    setCommanded(parsed)
    void api.motorsDirectPosition(motor.id, degToRad(parsed, span)).catch(onError)
  }

  const flags = motor.hw_error_flags
  return (
    <div style={{ borderTop: '1px solid var(--border)', padding: '6px 0' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ width: 84, color: 'var(--text)' }}>M{motor.id}</span>
        <input
          type="range"
          min={0}
          max={360}
          step={0.5}
          value={valid ? parsed : actualDeg}
          disabled={disabled}
          onChange={(e) => setTarget(e.target.value)}
          style={{ flex: 1, minWidth: 140 }}
        />
        <input
          type="number"
          min={0}
          max={360}
          step={0.5}
          value={target}
          disabled={disabled}
          onChange={(e) => setTarget(e.target.value)}
          style={{ width: 66 }}
        />
        <span style={{ color: 'var(--dimmer)' }}>deg</span>
        <button
          className="btn btn-primary"
          disabled={disabled || !valid}
          title={valid ? 'command this angle and hold it'
            : 'enter an angle between 0 and 360'}
          onClick={go}
        >
          Go
        </button>
        <button
          className="btn btn-secondary"
          disabled={disabled}
          title="mark where it is now, so the readout shows how far it has turned"
          onClick={() => setMark(actualDeg)}
        >
          Mark zero
        </button>
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 4, flexWrap: 'wrap',
                    color: 'var(--dim)' }}>
        <span>at {actualDeg.toFixed(1)}°</span>
        {mark !== null && (
          <span title={`marked at ${mark.toFixed(1)}°`}>
            {(actualDeg - mark >= 0 ? '+' : '') + (actualDeg - mark).toFixed(1)}°
            from mark
          </span>
        )}
        {commanded !== null && (
          <span style={{ color: arrived ? 'var(--ok)' : 'var(--warn)' }}>
            {arrived
              ? `holding ${commanded.toFixed(1)}°`
              : `${Math.abs(error ?? 0).toFixed(1)}° short of ${commanded.toFixed(1)}°`}
          </span>
        )}
        {motor.current_ma != null && (
          <span>{motor.current_ma.toFixed(0)} mA</span>
        )}
        {motor.temp_c != null && <span>{motor.temp_c.toFixed(0)} °C</span>}
        {flags && flags.length > 0 && (
          <span style={{ color: 'var(--err)' }}>{flags.join(' + ')}</span>
        )}
      </div>
    </div>
  )
}

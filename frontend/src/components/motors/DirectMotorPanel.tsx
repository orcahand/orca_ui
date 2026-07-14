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

export function DirectMotorPanel({
  torqueOn,
  locked,
}: {
  torqueOn: boolean
  locked: boolean
}) {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState<DirectMotorSnapshot | null>(null)
  const [values, setValues] = useState<Record<number, number>>({})
  const [busy, setBusy] = useState(false)
  const armed = control?.direct_motor_mode ?? false

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
      <summary style={{ cursor: 'pointer', color: 'var(--dimmer)' }}>
        Direct motor control (advanced)
      </summary>
      <div style={{ padding: '6px 0 0 0' }}>
        <div style={{ color: 'var(--warn)', marginBottom: 6 }}>
          Raw motor-space positions in radians — bypasses the joint mapping
          and ROM limits. Arming pauses the feedback loop and suspends joint
          sliders. Moves are capped at{' '}
          {(snapshot?.max_step_rad ?? 0.8).toFixed(1)} rad per command.
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
        {snapshot?.motors.map((motor) => (
          <MotorRow
            key={motor.id}
            motor={motor}
            value={values[motor.id] ?? motor.position}
            disabled={!armed || locked || !torqueOn}
            onSlide={(v) => setValues((prev) => ({ ...prev, [motor.id]: v }))}
            onError={fail}
          />
        ))}
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

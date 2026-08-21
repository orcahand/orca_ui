// Motor control with scripts/slider_joint.py parity: per-joint sliders
// seeded from the current pose (on mount and on every torque enable, never
// rewritten from the stream afterwards), torque enable/disable, neutral,
// and for feedback hands live meas/trim readouts. Everything is gated on
// the control-source owner: while an operation (or maintenance) owns the
// hand, manual commands are disabled with a tooltip naming the owner.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { JointInfo } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { sendTarget } from '../../state/commandBus'
import { useControlGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'
import { DirectMotorPanel } from './DirectMotorPanel'

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

function seedFromPose(
  joints: JointInfo[],
  pose: Record<string, number>,
): Record<string, number> {
  const values: Record<string, number> = {}
  for (const joint of joints) {
    const [lo, hi] = joint.rom
    const raw = pose[joint.id]
    values[joint.id] = clamp(Number.isFinite(raw) ? raw : 0, lo, hi)
  }
  return values
}

export function MotorPanel() {
  const handInfo = useAppStore((s) => s.handInfo)
  const status = useAppStore((s) => s.status)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const manualCal = useAppStore((s) => s.manualCal)
  const setManualCal = useAppStore((s) => s.setManualCal)
  const gate = useControlGate()

  const [values, setValues] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const [calStatus, setCalStatus] = useState<Record<string, 'busy' | 'done' | 'error'>>({})
  const [needReconnect, setNeedReconnect] = useState(false)
  const seeded = useRef(false)
  const wasLocked = useRef(false)

  // Re-seed after control returns to manual: a replay/teleop session moved
  // the hand, so the latched slider values are stale and the first touch
  // would yank the joint back to wherever the slider was left.
  useEffect(() => {
    if (wasLocked.current && gate.manualAllowed) seeded.current = false
    wasLocked.current = !gate.manualAllowed
  }, [gate.manualAllowed])

  const caps = status?.capabilities
  const torqueOn = control?.torque_enabled ?? false
  const feedback = caps?.feedback_loop ?? false
  const locked = !gate.manualAllowed
  const lockReason = gate.reason ?? undefined
  const directArmed = control?.direct_motor_mode ?? false
  // Motor limits/ratios unrecorded: _joint_to_motor_pos maps every joint to
  // None and the write is dropped, so a slider move is silently a no-op.
  const uncalibrated = handInfo?.calibration.motors === false

  // Latest pose the hand believes it is in (sensor-measured where available,
  // motor estimate elsewhere) — kept fresh for the sensor-cal "match" button.
  const believedPose = useRef<Record<string, number>>({})

  // Initial seed: latch the first available pose (measured, else estimate)
  // so opening the panel never yanks the hand.
  useStreamFrame((frames) => {
    believedPose.current = {
      ...frames.joints.estimate,
      ...frames.joints.measured,
    }
    if (seeded.current || !handInfo) return
    const pose = Object.keys(frames.joints.measured).length
      ? { ...frames.joints.estimate, ...frames.joints.measured }
      : frames.joints.estimate
    if (Object.keys(pose).length === 0) return
    seeded.current = true
    setValues(seedFromPose(handInfo.joints, pose))
  })

  if (!handInfo || !caps?.motors) return null
  const joints = handInfo.joints

  const enableTorque = async () => {
    setBusy(true)
    try {
      const { seed } = await api.torqueEnable()
      setValues(seedFromPose(joints, seed))
      seeded.current = true
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const disableTorque = async () => {
    try {
      await api.torqueDisable()
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  const goNeutral = async () => {
    try {
      await api.jointsNeutral()
      const neutral: Record<string, number> = {}
      for (const joint of joints) neutral[joint.id] = joint.neutral
      setValues(seedFromPose(joints, neutral))
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  const onSlide = (joint: JointInfo, value: number) => {
    setValues((prev) => ({ ...prev, [joint.id]: value }))
    if (manualCal) {
      // Sensor-cal mode never commands motors: the slider only dials the 3D
      // model to match the physically-posed hand.
      useAppStore.getState().setManualCalPose(joint.id, value)
    } else {
      sendTarget(joint.id, value)
    }
    // The joint moved after being anchored — its ✓ no longer describes the
    // current pose.
    if (calStatus[joint.id]) {
      setCalStatus((prev) => {
        const next = { ...prev }
        delete next[joint.id]
        return next
      })
    }
  }

  const hasEncoderJoints = joints.some((j) => j.encoder_backed)

  // Set every slider (and the 3D model) to the pose the hand currently
  // believes it is in, so only the joints that are actually off need dialing.
  const syncToBelieved = () => {
    const pose = believedPose.current
    const store = useAppStore.getState()
    setValues((prev) => {
      const next = { ...prev }
      for (const joint of joints) {
        const raw = pose[joint.id]
        if (!Number.isFinite(raw)) continue
        const v = clamp(raw, joint.rom[0], joint.rom[1])
        next[joint.id] = v
        store.setManualCalPose(joint.id, v)
      }
      return next
    })
    setCalStatus({})
  }

  const calibrateJoint = async (joint: JointInfo) => {
    const angle = values[joint.id] ?? clamp(0, joint.rom[0], joint.rom[1])
    setCalStatus((prev) => ({ ...prev, [joint.id]: 'busy' }))
    try {
      const result = await api.jointCalibrate(joint.id, angle)
      setCalStatus((prev) => ({ ...prev, [joint.id]: 'done' }))
      if (!result.loop_updated) setNeedReconnect(true)
      // encoder_calibrated / needs_calibration may have flipped.
      api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
      setError(null)
    } catch (error) {
      setCalStatus((prev) => ({ ...prev, [joint.id]: 'error' }))
      setError(String((error as Error).message ?? error))
    }
  }

  const toolbar = (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      {hasEncoderJoints && (
        <button
          className={manualCal ? 'btn btn-primary' : 'btn btn-secondary'}
          title="Manually calibrate the joint sensors: pose a joint with its
slider until the physical hand matches the 3D model, then press Set"
          onClick={() => {
            const entering = !manualCal
            setManualCal(entering)
            setCalStatus({})
            // Start from the believed pose so the model doesn't jump and
            // only the joints that are actually off need dialing.
            if (entering) syncToBelieved()
          }}
        >
          {manualCal ? 'Exit Sensor Cal' : 'Sensor Cal'}
        </button>
      )}
      {manualCal && (
        <button
          className="btn btn-secondary"
          title="set every slider (and the 3D model) back to the pose the
sensors currently report — then only dial the joints that are off"
          onClick={syncToBelieved}
        >
          Match sensed pose
        </button>
      )}
      {!torqueOn ? (
        <button
          className="btn btn-primary"
          disabled={busy || locked}
          title={lockReason}
          onClick={() => void enableTorque()}
        >
          Enable Torque
        </button>
      ) : (
        <button
          className="btn btn-danger"
          disabled={locked}
          title={lockReason}
          onClick={() => void disableTorque()}
        >
          Disable Torque
        </button>
      )}
      <button
        className="btn btn-secondary"
        disabled={!torqueOn || locked || uncalibrated}
        title={uncalibrated ? 'hand is not calibrated' : lockReason}
        onClick={() => void goNeutral()}
      >
        Neutral
      </button>
    </div>
  )

  const sliderLockReason = uncalibrated
    ? 'hand is not calibrated — use Direct motor control below'
    : directArmed
      ? 'direct motor mode is armed'
      : lockReason

  return (
    <Panel title="Motor Control" toolbar={toolbar}>
      {locked && (
        <div style={{ fontSize: 10, color: 'var(--warn)', marginBottom: 8 }}>
          {gate.reason} — manual control resumes when it releases
        </div>
      )}
      {!locked && uncalibrated && (
        <div style={{ fontSize: 10, color: 'var(--warn)', marginBottom: 8 }}>
          ⚠ NOT CALIBRATED — {handInfo.calibration.hint ?? 'the hand is not calibrated'}.
          Sliders are disabled: a joint target silently sends no motor
          command until motor limits are recorded. Use{' '}
          <strong>Direct motor control</strong> below to drive motors
          directly in the meantime.
        </div>
      )}
      {!locked && !uncalibrated && !torqueOn && (
        <div style={{ fontSize: 10, color: 'var(--dimmer)', marginBottom: 8 }}>
          enable torque to command joints — sliders re-seed from the current
          pose on enable
        </div>
      )}
      {manualCal && (
        <div style={{ fontSize: 10, color: 'var(--accent)', marginBottom: 8 }}>
          MANUAL SENSOR CALIBRATION — pose the physical hand by hand (torque
          can stay off; sliders only move the 3D model here, they never drive
          the motors). Dial each joint's slider until the model matches the
          real hand, then press <strong>Calibrate</strong>: that joint's
          sensor is re-anchored so its reading at this pose equals the slider
          angle. Repeat for as many joints as you like.
        </div>
      )}
      {needReconnect && (
        <div style={{ fontSize: 10, color: 'var(--warn)', marginBottom: 8 }}>
          anchors saved — reconnect to engage closed-loop control on the newly
          calibrated joint(s){' '}
          <button
            className="btn btn-secondary"
            style={{ marginLeft: 6 }}
            onClick={() => {
              setNeedReconnect(false)
              void api.reconnect().catch((error) =>
                setError(String((error as Error).message ?? error)),
              )
            }}
          >
            Reconnect
          </button>
        </div>
      )}
      <div>
        {joints.map((joint) => (
          <SliderRow
            key={joint.id}
            joint={joint}
            value={values[joint.id] ?? clamp(0, joint.rom[0], joint.rom[1])}
            disabled={
              manualCal
                ? locked
                : !torqueOn || locked || directArmed || uncalibrated
            }
            lockReason={manualCal ? lockReason : sliderLockReason}
            showFeedback={(feedback || manualCal) && joint.encoder_backed}
            calibrate={
              manualCal && joint.encoder_backed
                ? {
                    status: calStatus[joint.id],
                    disabled: locked,
                    onCalibrate: () => void calibrateJoint(joint),
                  }
                : undefined
            }
            onSlide={onSlide}
          />
        ))}
      </div>
      <DirectMotorPanel torqueOn={torqueOn} locked={locked} forceOpen={uncalibrated} />
    </Panel>
  )
}

function SliderRow({
  joint,
  value,
  disabled,
  lockReason,
  showFeedback,
  calibrate,
  onSlide,
}: {
  joint: JointInfo
  value: number
  disabled: boolean
  lockReason?: string
  showFeedback: boolean
  calibrate?: {
    status?: 'busy' | 'done' | 'error'
    disabled: boolean
    onCalibrate: () => void
  }
  onSlide: (joint: JointInfo, value: number) => void
}) {
  const [lo, hi] = joint.rom
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '3px 0',
        fontSize: 10,
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <span style={{ width: 84, textAlign: 'right', color: 'var(--text)' }}>
        {joint.id}
      </span>
      <span style={{ width: 30, color: 'var(--dimmer)', fontSize: 9, textAlign: 'right' }}>
        {lo.toFixed(0)}°
      </span>
      <input
        type="range"
        min={lo}
        max={hi}
        // Continuous, like the Tk slider: a 0.5° quantum turns a slow drag
        // into a staircase the 100 Hz PI loop chases step by step.
        step="any"
        value={value}
        disabled={disabled}
        title={lockReason}
        onChange={(e) => onSlide(joint, parseFloat(e.target.value))}
        style={{ flex: 1, height: 3, accentColor: 'var(--accent)', cursor: 'pointer' }}
      />
      <span style={{ width: 34, color: 'var(--dimmer)', fontSize: 9 }}>
        {hi > 0 ? `+${hi.toFixed(0)}` : hi.toFixed(0)}°
      </span>
      <AngleInput
        value={value}
        lo={lo}
        hi={hi}
        disabled={disabled}
        onCommit={(deg) => onSlide(joint, deg)}
      />
      {calibrate && (
        <button
          className="btn btn-secondary"
          style={{
            fontSize: 9,
            padding: '1px 6px',
            minWidth: 38,
            color:
              calibrate.status === 'done'
                ? 'var(--ok, #4caf50)'
                : calibrate.status === 'error'
                  ? 'var(--warn)'
                  : undefined,
          }}
          disabled={calibrate.disabled || calibrate.status === 'busy'}
          title={`Re-anchor ${joint.id}'s sensor: its reading at the current pose becomes ${value.toFixed(1)}°`}
          onClick={calibrate.onCalibrate}
        >
          {calibrate.status === 'busy'
            ? '…'
            : calibrate.status === 'done'
              ? '✓ Calibrate'
              : calibrate.status === 'error'
                ? '! Calibrate'
                : 'Calibrate'}
        </button>
      )}
      {showFeedback ? <FeedbackReadout jointId={joint.id} /> : <span style={{ width: 132 }} />}
    </div>
  )
}

// The angle readout, editable: type a value and press Enter to command it
// (clamped to the ROM). Shows the live slider value while not focused.
function AngleInput({
  value,
  lo,
  hi,
  disabled,
  onCommit,
}: {
  value: number
  lo: number
  hi: number
  disabled: boolean
  onCommit: (deg: number) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)

  const commit = (text: string) => {
    const parsed = parseFloat(text)
    if (Number.isFinite(parsed)) onCommit(clamp(parsed, lo, hi))
    setDraft(null)
  }

  return (
    <input
      type="number"
      step="any"
      value={draft ?? value.toFixed(1)}
      disabled={disabled}
      title="type an angle and press Enter"
      onFocus={(e) => {
        setDraft(value.toFixed(1))
        e.target.select()
      }}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit((e.target as HTMLInputElement).value)
        if (e.key === 'Escape') setDraft(null)
      }}
      onBlur={(e) => {
        if (draft !== null) commit(e.target.value)
      }}
      style={{
        width: 52,
        fontWeight: 600,
        color: 'var(--text)',
        textAlign: 'right',
        fontSize: 10,
        background: 'transparent',
        border: '1px solid var(--border, #444)',
        borderRadius: 3,
        padding: '1px 2px',
      }}
    />
  )
}

function FeedbackReadout({ jointId }: { jointId: string }) {
  const measRef = useRef<HTMLSpanElement>(null)
  const trimRef = useRef<HTMLSpanElement>(null)
  const lastUpdate = useRef(0)

  useStreamFrame((frames) => {
    const now = performance.now()
    if (now - lastUpdate.current < 100) return // ~10 Hz like the Tkinter UI
    lastUpdate.current = now
    const measured = frames.joints.measured[jointId]
    const trim = frames.joints.trim[jointId]
    if (measRef.current && measured !== undefined) {
      measRef.current.textContent = `meas ${measured >= 0 ? '+' : ''}${measured.toFixed(1)}°`
    }
    if (trimRef.current && trim !== undefined) {
      trimRef.current.textContent = `trim ${trim >= 0 ? '+' : ''}${trim.toFixed(1)}°`
    }
  })

  return (
    <span style={{ width: 132, display: 'inline-flex', gap: 6, fontSize: 9 }}>
      <span ref={measRef} style={{ color: 'var(--dim)', width: 64 }}>
        meas --
      </span>
      <span ref={trimRef} style={{ color: 'var(--dimmer)', width: 60 }}>
        trim --
      </span>
    </span>
  )
}

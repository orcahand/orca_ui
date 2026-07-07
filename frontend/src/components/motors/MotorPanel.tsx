// Motor control with scripts/slider_joint.py parity: per-joint sliders
// seeded from the current pose (on mount and on every torque enable, never
// rewritten from the stream afterwards), torque enable/disable, neutral,
// and for feedback hands live meas/trim readouts + tuning + loop stats.

import { useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { JointInfo } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { sendTarget } from '../../state/commandBus'
import { Panel } from '../common/Panel'
import { LoopStatsBar } from './LoopStatsBar'
import { TuningPanel } from './TuningPanel'

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

  const [values, setValues] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const seeded = useRef(false)

  const caps = status?.capabilities
  const torqueOn = control?.torque_enabled ?? false
  const feedback = caps?.feedback_loop ?? false

  // Initial seed: latch the first available pose (measured, else estimate)
  // so opening the panel never yanks the hand.
  useStreamFrame((frames) => {
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
    sendTarget(joint.id, value)
  }

  const toolbar = (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      {!torqueOn ? (
        <button className="btn btn-primary" disabled={busy} onClick={() => void enableTorque()}>
          Enable Torque
        </button>
      ) : (
        <button className="btn btn-danger" onClick={() => void disableTorque()}>
          Disable Torque
        </button>
      )}
      <button className="btn btn-secondary" disabled={!torqueOn} onClick={() => void goNeutral()}>
        Neutral
      </button>
    </div>
  )

  return (
    <Panel title="Motor Control" toolbar={toolbar}>
      {!torqueOn && (
        <div style={{ fontSize: 10, color: 'var(--dimmer)', marginBottom: 8 }}>
          enable torque to command joints — sliders re-seed from the current
          pose on enable
        </div>
      )}
      <div>
        {joints.map((joint) => (
          <SliderRow
            key={joint.id}
            joint={joint}
            value={values[joint.id] ?? clamp(0, joint.rom[0], joint.rom[1])}
            disabled={!torqueOn}
            showFeedback={feedback && joint.encoder_backed}
            onSlide={onSlide}
          />
        ))}
      </div>
      {feedback && <TuningPanel />}
      {feedback && <LoopStatsBar />}
    </Panel>
  )
}

function SliderRow({
  joint,
  value,
  disabled,
  showFeedback,
  onSlide,
}: {
  joint: JointInfo
  value: number
  disabled: boolean
  showFeedback: boolean
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
        step={0.5}
        value={value}
        disabled={disabled}
        onChange={(e) => onSlide(joint, parseFloat(e.target.value))}
        style={{ flex: 1, height: 3, accentColor: 'var(--accent)', cursor: 'pointer' }}
      />
      <span style={{ width: 34, color: 'var(--dimmer)', fontSize: 9 }}>
        {hi > 0 ? `+${hi.toFixed(0)}` : hi.toFixed(0)}°
      </span>
      <span style={{ width: 52, fontWeight: 600, color: 'var(--text)', textAlign: 'right' }}>
        →{value >= 0 ? '+' : ''}
        {value.toFixed(1)}°
      </span>
      {showFeedback ? <FeedbackReadout jointId={joint.id} /> : <span style={{ width: 132 }} />}
    </div>
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

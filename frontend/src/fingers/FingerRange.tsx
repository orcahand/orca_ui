// Step 3 — range: the open and the closed end of every joint, in joint
// degrees read through the coupling. Hold the finger's motors and jog the
// joint itself — every motor of the coupling turns by its share of the
// inverse, so the other joints stay put — to an end and Set it. Set zero
// records the shaft positions at which every joint reads 0°.

import { useMemo, useRef, useState } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'
import { useOperationActive } from '../state/operationStore'
import { useBenchStore } from '../bench/benchStore'
import { formatDeg, useMotorLive } from '../bench/useMotorLive'
import { type Coupling, type MotorJoint, couplingProblem, couplingsOf, jointAnglesOf, shaftDeltaFor } from './coupling'
import { motorLabel } from './FingerTendons'
import { fractionOf, groupsOf, hasRange, resolve, useFingerStore } from './fingerStore'

const JOINT_STEP_DEG = 5
const JOG_REPEAT_MS = 180
const JOG_REPEAT_AFTER_MS = 400
// Below the backend's 0.8 rad per-write cap, so every motor's share is one accepted write.
const MAX_SHAFT_STEP_DEG = 40
const DEG = Math.PI / 180

// Hold or release every motor of the joint's coupling, and jog the joint in
// joint degrees through the inverse of the coupling.
function JointHandles({
  joint,
  coupling,
  connected,
  positions,
}: {
  joint: MotorJoint
  coupling: Coupling
  connected: boolean
  positions: React.MutableRefObject<Record<string, number>>
}) {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const motors = useBenchStore((s) => s.motors)
  const opActive = useOperationActive()
  const [busy, setBusy] = useState(false)
  const [jogging, setJogging] = useState(false)
  const repeat = useRef<{ timer: number | null; interval: number | null }>({ timer: null, interval: null })
  const heldSet = new Set(control?.held_motors ?? [])
  const allHeld = coupling.motors.every((m) => heldSet.has(m))
  const manual = control?.control_source === 'manual'
  const canHold = connected && manual && !opActive && !busy
  const canJog = connected && manual && !opActive && allHeld && couplingProblem(coupling) === null

  const toggleHold = async () => {
    setBusy(true)
    try {
      for (const id of coupling.motors) if (heldSet.has(id) !== !allHeld) await api.motorTorque(id, !allHeld)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
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
  const jogOnce = async (direction: 1 | -1) => {
    try {
      const deltas = shaftDeltaFor(coupling, joint.name, direction * JOINT_STEP_DEG)
      if (!deltas) throw new Error(`${joint.name}: the coupling cannot be inverted`)
      const largest = Math.max(...Object.values(deltas).map(Math.abs))
      if (largest > MAX_SHAFT_STEP_DEG)
        throw new Error(
          `${joint.name}: ${JOINT_STEP_DEG}° of joint needs ${largest.toFixed(0)}° of shaft — the gains look too small`,
        )
      for (const motor of coupling.motors) {
        if (positions.current[String(motor)] === undefined)
          throw new Error(`${motorLabel(motors, motor)}: no live position yet`)
      }
      if (!useAppStore.getState().control?.direct_motor_mode) await api.motorsDirectMode(true)
      for (const motor of coupling.motors) {
        const target = positions.current[String(motor)] + deltas[motor]
        await api.motorsDirectPosition(motor, target * DEG)
        // Optimistic: a held button keeps stepping from where the last write asked for.
        positions.current[String(motor)] = target
      }
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
      stopRepeat()
    }
  }
  const startRepeat = (direction: 1 | -1) => {
    if (!canJog) return
    setJogging(true)
    void jogOnce(direction)
    repeat.current.timer = window.setTimeout(() => {
      repeat.current.interval = window.setInterval(() => void jogOnce(direction), JOG_REPEAT_MS)
    }, JOG_REPEAT_AFTER_MS)
  }

  const names = coupling.motors.map((m) => motorLabel(motors, m)).join(', ')
  const title = canJog
    ? `${JOINT_STEP_DEG}° of ${joint.name} (hold to repeat); the other joints of the finger stay put`
    : `hold ${names} to jog the joint`
  return (
    <span className="finger-jog">
      <button
        className={`btn ${allHeld ? 'btn-danger' : 'btn-info'}`}
        disabled={!canHold}
        title={allHeld ? `release ${names}: the motors turn freely` : `hold ${names}: torque on, the finger pins where it is`}
        onClick={() => void toggleHold()}
      >
        {allHeld ? 'release' : 'hold'}
      </button>
      <button
        className="btn btn-secondary"
        disabled={!canJog}
        title={title}
        onPointerDown={() => startRepeat(-1)}
        onPointerUp={stopRepeat}
        onPointerLeave={stopRepeat}
        onPointerCancel={stopRepeat}
      >
        −
      </button>
      <button
        className="btn btn-secondary"
        disabled={!canJog}
        title={title}
        onPointerDown={() => startRepeat(1)}
        onPointerUp={stopRepeat}
        onPointerLeave={stopRepeat}
        onPointerCancel={stopRepeat}
      >
        +
      </button>
      {jogging && <small>jogging…</small>}
    </span>
  )
}

function RangeRow({
  joint,
  coupling,
  connected,
  locked,
  positions,
}: {
  joint: MotorJoint
  coupling: Coupling | undefined
  connected: boolean
  locked: boolean
  positions: React.MutableRefObject<Record<string, number>>
}) {
  const joints = useFingerStore((s) => s.joints)
  const patchJoint = useFingerStore((s) => s.patchJoint)
  const zeros = useFingerStore((s) => s.zeros)
  const setError = useAppStore((s) => s.setError)
  const index = joints.findIndex((j) => j.name === joint.name)
  const liveAngle = useRef<number | null>(null)
  const angleRef = useRef<HTMLSpanElement>(null)
  const barRef = useRef<HTMLSpanElement>(null)
  const problem = coupling ? couplingProblem(coupling) : 'no tendon'

  useMotorLive((frames) => {
    const angle = coupling && !problem ? jointAnglesOf([coupling], zeros, frames.motors.positions)[joint.name] : undefined
    liveAngle.current = angle ?? null
    if (angleRef.current) angleRef.current.textContent = formatDeg(angle)
    if (barRef.current) {
      const f = angle === undefined ? null : fractionOf(joint, angle)
      barRef.current.style.width = f === null ? '0%' : `${(f * 100).toFixed(1)}%`
    }
  })

  const capture = (which: 'open_deg' | 'closed_deg') => {
    const value = liveAngle.current
    if (value === null) {
      setError(`${joint.name}: no joint angle to capture — ${problem ?? 'no live shaft reading yet'}`)
      return
    }
    patchJoint(index, { [which]: Math.round(value * 10) / 10 })
  }
  const edit = (which: 'open_deg' | 'closed_deg', text: string) => {
    const value = parseFloat(text)
    patchJoint(index, { [which]: Number.isFinite(value) ? value : null })
  }
  const span = joint.open_deg !== null && joint.closed_deg !== null ? joint.closed_deg - joint.open_deg : null

  return (
    <div className={`finger-row ${hasRange(joint) && !problem ? '' : 'incomplete'}`}>
      <div className="finger-row-main">
        <span className="finger-name finger-name-static">{joint.name}</span>
        <span className="finger-live" title="live joint angle, through the coupling">
          <span ref={angleRef}>—</span>
          <i className="finger-live-bar">
            <span ref={barRef} />
          </i>
        </span>
        {(['open_deg', 'closed_deg'] as const).map((which) => (
          <span key={which} className="finger-end">
            <span className="finger-end-name">{which === 'open_deg' ? 'open' : 'closed'}</span>
            <input
              type="number"
              step={0.1}
              value={joint[which] ?? ''}
              placeholder="—"
              disabled={locked}
              onChange={(e) => edit(which, e.target.value)}
            />
            <span className="bench-unit">°</span>
            <button
              className="btn btn-primary"
              disabled={!connected || locked || problem !== null}
              title={`capture the live joint angle as the ${which === 'open_deg' ? 'open' : 'closed'} end`}
              onClick={() => capture(which)}
            >
              Set
            </button>
          </span>
        ))}
        <span className="finger-span">
          {problem
            ? `${problem} — fix in Coupling`
            : span === null
              ? 'capture both ends'
              : Math.abs(span) < 1
                ? 'the ends are the same'
                : `${Math.abs(span).toFixed(1)}° of travel${span < 0 ? ', closing backward' : ''}`}
        </span>
        <span className="finger-row-tools">
          {coupling && (
            <JointHandles joint={joint} coupling={coupling} connected={connected} positions={positions} />
          )}
        </span>
      </div>
    </div>
  )
}

export function FingerRange({ connected, locked }: { connected: boolean; locked: boolean }) {
  const joints = useFingerStore((s) => s.joints)
  const tendons = useFingerStore((s) => s.tendons)
  const setZeros = useFingerStore((s) => s.setZeros)
  const motors = useBenchStore((s) => s.motors)
  const setError = useAppStore((s) => s.setError)
  const resolved = useMemo(() => resolve(joints, tendons), [joints, tendons])
  const couplings = useMemo(() => couplingsOf(resolved), [resolved])
  const couplingOf = (joint: MotorJoint) => couplings.find((c) => c.joints.includes(joint))
  const livePositions = useRef<Record<string, number>>({})
  useMotorLive((frames) => {
    livePositions.current = frames.motors.positions
  })

  // Zero: the shaft positions at which every joint reads 0°. Only changes
  // what future captures and typed angles mean; captured ends keep their numbers.
  const captureZero = () => {
    const used = [...new Set(resolved.flatMap((j) => j.terms.map((t) => t.motor)))]
    const zeros: Record<string, number> = {}
    for (const motor of used) {
      const pos = livePositions.current[String(motor)]
      if (pos === undefined) {
        setError(`${motorLabel(motors, motor)}: no live position yet`)
        return
      }
      zeros[String(motor)] = Math.round(pos * 10) / 10
    }
    setZeros(zeros)
  }

  return (
    <section className="panel finger-setup">
      <div className="panel-header">
        <h2>Range</h2>
        <small className="finger-hint">
          hold a finger's motors and jog each joint to its ends with − and +, then Set them; a jog moves
          only that joint, so if another one bends the coupling is wrong
        </small>
        <button
          className="btn btn-secondary"
          disabled={locked || resolved.length === 0 || !connected}
          title="take the present shaft positions as every joint's 0° (straighten the hand first)"
          onClick={captureZero}
        >
          Set zero here
        </button>
      </div>
      {resolved.length === 0 ? (
        <p className="panel-empty">No joints yet — define them in the Coupling step.</p>
      ) : (
        groupsOf(resolved).map(({ group, joints: members }) => (
          <details key={group || '\u0000'} className="finger-finger" open>
            <summary>
              {group || 'ungrouped'}
              <small>
                {members.filter((j) => hasRange(j) && couplingProblem(couplingOf(j)!) === null).length}/
                {members.length} ready
              </small>
            </summary>
            {members.map((joint) => (
              <RangeRow
                key={joint.name}
                joint={joint}
                coupling={couplingOf(joint)}
                connected={connected}
                locked={locked}
                positions={livePositions}
              />
            ))}
          </details>
        ))
      )}
    </section>
  )
}

// Step 3 — range: the open and the closed end of every joint, in joint
// degrees read through the coupling. Release the motors, move a joint by
// hand to an end and Set it — or hold its first tendon's motor and jog
// there. Set zero records the shaft positions at which every joint reads 0°.

import { useMemo, useRef } from 'react'
import { useAppStore } from '../state/appStore'
import { useBenchStore } from '../bench/benchStore'
import { formatDeg, useMotorLive } from '../bench/useMotorLive'
import { type Coupling, type MotorJoint, couplingProblem, couplingsOf, jointAnglesOf } from './coupling'
import { MotorHandles, motorLabel } from './FingerTendons'
import { fractionOf, groupsOf, hasRange, resolve, useFingerStore } from './fingerStore'

function RangeRow({
  joint,
  coupling,
  connected,
  locked,
}: {
  joint: MotorJoint
  coupling: Coupling | undefined
  connected: boolean
  locked: boolean
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
  const motors = useBenchStore((s) => s.motors)
  const firstMotor = joint.terms[0]?.motor ?? null

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
        <span className="finger-row-tools" title={`jog ${motorLabel(motors, firstMotor)}`}>
          <MotorHandles motorId={firstMotor} connected={connected} />
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
          release the motors, move a joint by hand to each end and Set it — or hold and jog there
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
              <RangeRow key={joint.name} joint={joint} coupling={couplingOf(joint)} connected={connected} locked={locked} />
            ))}
          </details>
        ))
      )}
    </section>
  )
}

// The fingers mode, in the order a hand goes on the bench: tendons onto
// motors, the coupling between tendons and joints, each joint's range, then
// the joints driven. One step on screen at a time; the bar says how far
// each has got, and a run in progress lands on Control.

import { useEffect, useMemo } from 'react'
import { useOperationStore } from '../state/operationStore'
import { couplingProblem, couplingsOf } from './coupling'
import { FingerControl } from './FingerControl'
import { FingerCoupling } from './FingerCoupling'
import { FingerPresets } from './FingerPresets'
import { FingerRange } from './FingerRange'
import { FingerTendons } from './FingerTendons'
import { STEPS, hasRange, readyJoints, resolve, useFingerStore } from './fingerStore'

export function FingerWorkflow({ connected }: { connected: boolean }) {
  const step = useFingerStore((s) => s.step)
  const setStep = useFingerStore((s) => s.setStep)
  const tendons = useFingerStore((s) => s.tendons)
  const joints = useFingerStore((s) => s.joints)
  const engaged = useOperationStore(
    (s) => s.operation?.kind === 'finger_control' && s.operation.state !== 'done' && s.operation.state !== 'error',
  )
  useEffect(() => {
    if (engaged) setStep('control')
  }, [engaged, setStep])

  const status = useMemo(() => {
    const resolved = resolve(joints, tendons)
    const solvable = couplingsOf(resolved).filter((c) => couplingProblem(c) === null).flatMap((c) => c.joints)
    return {
      tendons: `${tendons.filter((t) => t.motor !== null).length}/${tendons.length} on a motor`,
      coupling: `${solvable.length}/${joints.length} solvable`,
      range: `${resolved.filter(hasRange).length}/${joints.length} captured`,
      control: `${readyJoints(resolved).length} ready`,
    }
  }, [tendons, joints])

  return (
    <>
      <nav className="finger-steps" aria-label="finger setup steps">
        {STEPS.map((s) => (
          <button
            key={s.step}
            className={`finger-step ${step === s.step ? 'on' : ''}`}
            title={s.title}
            aria-current={step === s.step ? 'step' : undefined}
            onClick={() => setStep(s.step)}
          >
            <span>{s.label}</span>
            <small>{status[s.step]}</small>
          </button>
        ))}
      </nav>
      <FingerPresets locked={engaged} />
      {step === 'tendons' && <FingerTendons connected={connected} locked={engaged} />}
      {step === 'coupling' && <FingerCoupling locked={engaged} />}
      {step === 'range' && <FingerRange connected={connected} locked={engaged} />}
      {step === 'control' && <FingerControl connected={connected} />}
    </>
  )
}

// Tests tab: hardware tests for a plan on the connected hand. Hands-on steps
// come first (a person acts or watches and decides), then one automatic run
// covers every check, compare steps side by side for main and the branch.
// Everything lands in the bench folder, whose paths the cards offer to copy.

import { useMemo } from 'react'
import { AutoCard } from '../hwtests/AutoCard'
import { SessionCard, StartCard } from '../hwtests/SessionCards'
import { StepCounts, StepList } from '../hwtests/StepList'
import { StepPanel } from '../hwtests/StepPanel'
import { Panel } from '../common/Panel'
import {
  allSteps,
  findStep,
  isHandsOn,
  useHardwareTestsPolling,
  useHardwareTestsStore,
} from '../../state/hardwareTestsStore'
import '../hwtests/hwtests.css'

export function TestsView() {
  useHardwareTestsPolling()
  const enabled = useHardwareTestsStore((s) => s.enabled)
  const plans = useHardwareTestsStore((s) => s.plans)
  const session = useHardwareTestsStore((s) => s.session)
  const pollError = useHardwareTestsStore((s) => s.pollError)
  const selected = useHardwareTestsStore((s) => s.selected)

  const steps = useMemo(() => allSteps(session), [session])
  const handsOn = steps.filter(({ step }) => isHandsOn(step))
  const automatic = steps.filter(({ step }) => !isHandsOn(step))
  const open = findStep(session, selected)

  if (enabled === null) {
    return (
      <div className="detecting-card">
        {pollError ? `Tests unavailable: ${pollError}` : 'loading tests…'}
      </div>
    )
  }
  if (!enabled) {
    return (
      <Panel title="Hardware tests">
        <div className="panel-empty">
          The Tests tab is off. It turns on when the console runs a development orca_core or is
          started with --hardware-tests.
        </div>
      </Panel>
    )
  }

  return (
    <div className="hwt-view">
      {pollError && (
        <div className="hwt-hint warn">Lost contact with the tests backend: {pollError}</div>
      )}
      {!session ? (
        <StartCard plans={plans} />
      ) : (
        <div className="hwt-layout">
          <div className="hwt-column">
            <SessionCard session={session} />
            <Panel title="Hands-on" toolbar={<StepCounts steps={handsOn} />}>
              <div className="hwt-hint">
                Do these first, in order: open a step, follow it, then decide. Live readings are
                recorded while a step is open.
              </div>
              <StepList
                steps={handsOn}
                session={session}
                empty="This plan has no hands-on steps."
              />
            </Panel>
            <AutoCard steps={automatic} session={session} />
          </div>
          <div className="hwt-column hwt-panel-column">
            {open ? (
              <StepPanel key={open.step.id} stepRef={open} session={session} />
            ) : (
              <Panel title="No step open">
                <div className="panel-empty">Pick a step on the left to see what to do.</div>
              </Panel>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

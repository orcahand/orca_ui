// Tension on its own: wind → ramp → hold → release flow. The phase stepper
// mirrors the transport-bar state; while the motors hold, the awaiting_input
// options (Release) take over the card as the hold callout — that hold is the
// only moment the user has to do something with their hands.
//
// The winding pass is optional. Skipping it holds the motors where they
// already are, which is what you want on a hand whose spools are already
// close: the wind drives every tendon to its stall in both directions first,
// and on an already-tensioned hand that is motion for nothing.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { TensionHoldCallout, TensionSteps } from './TensionGuide'

const PHASES = ['winding', 'ramp', 'holding', 'released']
// Without the wind there is nothing to ramp down from, so core emits neither.
// Carrying them greyed would read as two phases that silently failed.
const HOLD_ONLY_PHASES = ['holding', 'released']

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function TensionCard() {
  const gate = useStartGate('motors')
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation !== null &&
    operation.kind === 'tension' &&
    isOperationActive(operation)
      ? operation
      : null

  const [wind, setWind] = useState(true)

  const start = () =>
    void api.operationStart('tension', { move_motors: wind }).catch(fail)

  // What the run in flight was actually started with, which outlives a page
  // reload; the local tickbox only describes the next run.
  const ranWithWind = active ? active.params.move_motors !== false : wind
  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null

  return (
    <div className="setup-card">
      <div className="setup-card-title">Tension the tendons</div>
      <p className="setup-copy">
        {ranWithWind
          ? 'The motors wind the tendons in and hold them there while you tighten the spools by hand.'
          : 'The motors hold where they are, without winding first, while you tighten the spools by hand.'}
      </p>
      {active ? (
        <>
          <PhaseStepper
            current={active.phase}
            phases={ranWithWind ? PHASES : HOLD_ONLY_PHASES}
          />
          {awaiting ? (
            <TensionHoldCallout options={awaiting.options} />
          ) : (
            <>
              {active.detail && (
                <div className="setup-card-detail">{active.detail}</div>
              )}
              <TensionSteps started wind={ranWithWind} />
            </>
          )}
        </>
      ) : (
        <>
          <TensionSteps wind={wind} />
          <div className="setup-note">
            Always calibrate afterwards — tensioning changes the tendon lengths.
          </div>
          <label className="joint-check">
            <input
              type="checkbox"
              checked={!wind}
              onChange={(e) => setWind(!e.target.checked)}
            />
            Hold still — skip the winding pass
          </label>
          <div>
            <button
              className="btn btn-primary"
              disabled={gate.blocked}
              title={gate.reason ?? undefined}
              onClick={start}
            >
              Start tensioning
            </button>
          </div>
          {gate.blocked && (
            <div className="setup-card-reason">{gate.reason}</div>
          )}
        </>
      )}
    </div>
  )
}

function PhaseStepper({
  current,
  phases,
}: {
  current: string | null
  phases: string[]
}) {
  // acquiring/connecting precede the stepper phases: index -1 = all pending.
  const index = current ? phases.indexOf(current) : -1
  return (
    <div className="phase-stepper">
      {phases.map((phase, i) => (
        <span
          key={phase}
          className={`phase-step${
            i === index ? ' active' : i < index ? ' done' : ''
          }`}
        >
          {phase}
        </span>
      ))}
    </div>
  )
}

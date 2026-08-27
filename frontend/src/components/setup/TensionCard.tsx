// Tension on its own: full wind → ramp → hold → release flow. The phase
// stepper mirrors the transport-bar state; while the motors hold, the
// awaiting_input options (Release) take over the card as the hold callout —
// that hold is the only moment the user has to do something with their hands.

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

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function TensionCard() {
  const gate = useStartGate('motors')
  const operation = useOperationStore((s) => s.operation)
  // Hold-only mode (the CLI's --no-move-motors): skip the winding motion
  // and go straight to the stall-hold for manual spool work.
  const [moveMotors, setMoveMotors] = useState(true)
  const active =
    operation !== null &&
    operation.kind === 'tension' &&
    isOperationActive(operation)
      ? operation
      : null

  const start = () =>
    void api
      .operationStart('tension', { move_motors: moveMotors })
      .catch(fail)

  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null

  return (
    <div className="setup-card">
      <div className="setup-card-title">Tension the tendons</div>
      <p className="setup-copy">
        The motors wind the tendons in and hold them there while you tighten
        the spools by hand.
      </p>
      {active ? (
        <>
          <PhaseStepper
            current={active.phase}
            phases={moveMotors ? PHASES : ['holding', 'released']}
          />
          {awaiting ? (
            <TensionHoldCallout options={awaiting.options} />
          ) : (
            <>
              {active.detail && (
                <div className="setup-card-detail">{active.detail}</div>
              )}
              <TensionSteps started />
            </>
          )}
        </>
      ) : (
        <>
          <TensionSteps />
          <div className="setup-note">
            Always calibrate afterwards — tensioning changes the tendon lengths.
          </div>
          <label className="joint-check">
            <input
              type="checkbox"
              checked={!moveMotors}
              onChange={(e) => setMoveMotors(!e.target.checked)}
            />
            Hold only — skip the winding motion
          </label>
          <p className="setup-option-hint">
            {moveMotors
              ? 'The motors first wind the tendons taut, then hold. Tick to ' +
                'go straight to the hold with no motor movement at all ' +
                '(the CLI’s --no-move-motors).'
              : 'No movement: the motors stall-hold right where the hand ' +
                'is, and you tension the spools against that.'}
          </p>
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
  phases = PHASES,
}: {
  current: string | null
  // Hold-only runs skip winding/ramp entirely.
  phases?: string[]
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

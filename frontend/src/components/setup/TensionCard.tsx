// Tension card: full wind → ramp → hold → release flow. The phase stepper
// mirrors the transport-bar state; while the motors hold, the awaiting_input
// options (Release) render as a prominent button.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'

const PHASES = ['winding', 'ramp', 'holding', 'released']

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

  const start = () =>
    void api.operationStart('tension', { move_motors: true }).catch(fail)

  return (
    <div className="setup-card">
      <div className="setup-card-title">Tension</div>
      <p className="setup-card-hint">
        Winds the tendons until the motors stall, ramps the current down,
        then holds while you tension the spools by hand. Release ends the
        hold and switches torque off.
      </p>
      {active ? (
        <>
          <PhaseStepper current={active.phase} />
          {active.detail && (
            <div className="setup-card-detail">{active.detail}</div>
          )}
          {active.state === 'awaiting_input' &&
            active.awaiting?.options.map((option) => (
              <button
                key={option}
                className="btn btn-info setup-release"
                onClick={() => void api.operationInput(option).catch(fail)}
              >
                {option}
              </button>
            ))}
        </>
      ) : (
        <>
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

function PhaseStepper({ current }: { current: string | null }) {
  // acquiring/connecting precede the stepper phases: index -1 = all pending.
  const index = current ? PHASES.indexOf(current) : -1
  return (
    <div className="phase-stepper">
      {PHASES.map((phase, i) => (
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

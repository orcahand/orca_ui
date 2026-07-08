// Guided bring-up wizard: (tension → calibrate) × rounds with confirm gates
// between rounds. The backend op lands in M6 — this card is built against
// its frozen contract: phases alternate "tension"/"calibrating" with detail
// "round i/N"; between rounds it parks in awaiting_input
// {options: ["Continue", "Finish"]}; tension holds await Release.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'

const ROUND_RE = /round (\d+)\/(\d+)/

// A wizard tension stage reports the tension sub-phases (winding → ramp →
// holding → released) as its phase; the calibrate stage reports
// "calibrating". Map either onto the two timeline cells.
const TENSION_PHASES = new Set([
  'tension',
  'winding',
  'ramp',
  'holding',
  'released',
])

function stageOf(phase: string | null): 'tension' | 'calibrating' | null {
  if (phase && TENSION_PHASES.has(phase)) return 'tension'
  if (phase === 'calibrating' || phase === 'calibrate') return 'calibrating'
  return null
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function WizardCard() {
  const gate = useStartGate('motors')
  const operation = useOperationStore((s) => s.operation)
  const [rounds, setRounds] = useState(3)

  const active =
    operation !== null &&
    operation.kind === 'wizard' &&
    isOperationActive(operation)
      ? operation
      : null

  const start = () =>
    void api.operationStart('wizard', { rounds }).catch(fail)

  const match = active?.detail?.match(ROUND_RE)
  const currentRound = match ? parseInt(match[1], 10) : null
  const totalRounds = match
    ? parseInt(match[2], 10)
    : Number(active?.params.rounds ?? rounds)

  return (
    <div className="setup-card">
      <div className="setup-card-title">Bring-up Wizard</div>
      <p className="setup-card-hint">
        Guided first-time setup: alternates tensioning and calibration for a
        number of rounds, with a confirm gate between rounds.
      </p>
      {active ? (
        <>
          <WizardTimeline
            totalRounds={totalRounds}
            currentRound={currentRound}
            phase={active.phase}
            awaiting={active.state === 'awaiting_input'}
          />
          {active.detail && (
            <div className="setup-card-detail">
              {active.phase}
              {active.detail ? ` — ${active.detail}` : ''}
            </div>
          )}
          {active.state === 'awaiting_input' && active.awaiting && (
            <div className="setup-card-row">
              <span className="setup-card-detail">
                {active.awaiting.prompt}
              </span>
              {active.awaiting.options.map((option) => (
                <button
                  key={option}
                  className="btn btn-primary"
                  onClick={() => void api.operationInput(option).catch(fail)}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="setup-card-row">
            <label className="joint-check">
              rounds
              <select
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="btn btn-primary"
              disabled={gate.blocked}
              title={gate.reason ?? undefined}
              onClick={start}
            >
              Start wizard
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

function WizardTimeline({
  totalRounds,
  currentRound,
  phase,
  awaiting,
}: {
  totalRounds: number
  currentRound: number | null
  phase: string | null
  awaiting: boolean
}) {
  const stage = stageOf(phase)
  const cellClass = (round: number, cell: 'tension' | 'calibrating') => {
    if (currentRound === null || round > currentRound) return ''
    if (round < currentRound) return ' done'
    // round === currentRound
    if (awaiting) return ' done' // parked between rounds: both stages done
    if (stage === cell) return ' active'
    if (cell === 'tension' && stage === 'calibrating') return ' done'
    return ''
  }
  return (
    <div className="wizard-timeline">
      {Array.from({ length: totalRounds }, (_, i) => i + 1).map((round) => (
        <span key={round} className="wizard-round">
          <span className="wizard-round-label">R{round}</span>
          <span className={`phase-step${cellClass(round, 'tension')}`}>
            tension
          </span>
          <span className={`phase-step${cellClass(round, 'calibrating')}`}>
            calibrate
          </span>
        </span>
      ))}
    </div>
  )
}

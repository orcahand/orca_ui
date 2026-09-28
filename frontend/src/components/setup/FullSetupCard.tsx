// The Setup tab's primary action: (tension → calibrate) × rounds under one
// maintenance lease, with a confirm gate between rounds. Backend op kind is
// still "wizard"; the card is written for someone bringing up a hand for the
// first time, so it leads with what to do and why the rounds repeat.
//
// Phases alternate the tension sub-phases and "calibrating", with detail
// "round i/N"; between rounds the op parks in awaiting_input
// {options: ["Continue", "Finish"]}; tension holds await Release.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { HoverNote } from '../common/HoverNote'
import { SetupStep, TensionHoldCallout } from './TensionGuide'

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

export function FullSetupCard() {
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

  // The tension hold and the between-rounds gate both park in awaiting_input;
  // only the hold offers Release.
  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null
  const holding = awaiting?.options.includes('Release') ?? false

  return (
    <div className="setup-card setup-hero">
      <div className="setup-hero-head">
        <div className="setup-card-title">Full setup</div>
        <span className="setup-badge">start here</span>
      </div>
      <p className="setup-copy">
        Start here on a hand you have just built, or whenever the fingers feel
        loose and poses come out short.
      </p>

      {active ? (
        <>
          <WizardTimeline
            totalRounds={totalRounds}
            currentRound={currentRound}
            phase={active.phase}
            awaiting={awaiting !== null && !holding}
          />
          {holding ? (
            <TensionHoldCallout options={awaiting!.options} />
          ) : awaiting ? (
            // Between rounds: the phase/detail still names the last
            // calibration step, so drop it — nothing is moving.
            <div className="setup-callout">
              <div className="setup-callout-title">{awaiting.prompt}</div>
              <p className="setup-copy">
                Run another round if the spools still took up slack this time.
                If they were already firm when you ratcheted them, the hand is
                done.
              </p>
              <div className="setup-card-row">
                {awaiting.options.map((option) => (
                  <button
                    key={option}
                    className={`btn ${
                      option === 'Continue' ? 'btn-primary' : 'btn-secondary'
                    }`}
                    onClick={() => void api.operationInput(option).catch(fail)}
                  >
                    {option === 'Continue'
                      ? 'Run another round'
                      : 'Finish — the hand is set up'}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              <div className="setup-card-detail">
                {active.phase}
                {active.detail ? ` — ${active.detail}` : ''}
              </div>
              {stageOf(active.phase) === 'calibrating' && (
                <p className="setup-copy dim">
                  The hand is driving each joint to its hardstops on its own.
                  Keep hands and objects clear.
                </p>
              )}
            </>
          )}
        </>
      ) : (
        <div className="setup-hero-body">
          <div className="setup-round-shape">
            <span className="setup-section-title">Each round</span>
            <ol className="setup-steps">
              <SetupStep n={1} title="You tension the tendons">
                The motors wind the tendons in and hold them there. With the
                ratchet, turn the top spool of each motor clockwise until the
                tendon feels firm — you should hear it click. A little give is
                fine; over-tightening makes the hand worse, not better. Then
                press Release.
              </SetupStep>
              <SetupStep n={2} title="The hand calibrates itself">
                It drives every joint to its hardstops and records the range it
                can reach. Keep hands and objects clear while it runs.
              </SetupStep>
            </ol>
          </div>

          <div className="setup-hero-side">
            <div className="setup-card-row">
              <button
                className="btn btn-primary btn-hero"
                disabled={gate.blocked}
                title={gate.reason ?? undefined}
                onClick={start}
              >
                Start full setup
              </button>
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
            </div>
            {gate.blocked ? (
              <div className="setup-card-reason">{gate.reason}</div>
            ) : (
              <HoverNote label="Why several rounds?">
                A new hand is spooled by hand, so the tendons start out slack.
                Tensioning takes that slack out, and calibration then pulls the
                tendons through their whole range and brings out what was left.
                Each round leaves less. Three is usual for a freshly built
                hand, and you can stop after any of them.
              </HoverNote>
            )}
          </div>
        </div>
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

// Guided tensioning as an installer-style dialog over the console. The
// operation drives the steps (centre → range check → score → tension, per
// round); this mirrors its snapshot and answers its prompts. Enter takes the
// primary answer. The dialog outlives the run until closed, so the final
// score stays readable.
//
// The run's scoring (extra.scoring) picks what the rows say: fraction scoring
// shows percent of the expected travel with kept scores; slack scoring shows
// the slack in motor degrees and the ends reached. The ratchet step lists the
// clicks each joint's missing travel needs, rounded down, so a round aims a
// little loose; the tension sweep after calibration counts the last clicks.

import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type {
  GuidedTensionExtra,
  ModelMetadata,
  MotorSpread,
  OperationSnapshot,
  SpreadStatus,
  TensionStep,
  RangeStage,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { isOperationActive } from '../../state/operationStore'
import { EXTRA_DEG, PULL_MORE } from '../../state/tensionFlow'
import type { PreviewMode } from './TensionPreview'
import { TowerFaces } from './TowerFaces'
import {
  DEFAULT_PASS,
  DEFAULT_PASS_SLACK,
  PASS_BOUNDS_DEG,
  PASS_BOUNDS_PCT,
  PASS_GROUPS,
  savePassFractions,
  savePassSlack,
  type PassFractions,
  type PassSlack,
} from './guidedSettings'

const TensionPreview = lazy(() =>
  import('./TensionPreview').then((m) => ({ default: m.TensionPreview })),
)

// The loop as the sidebar shows it: ratchet → move each finger → score, and round again.
const BEFORE_STAGES: { key: TensionStep; title: string; note: string }[] = [
  { key: 'tension', title: 'Ratchet', note: 'the listed spools' },
]
const AFTER_STAGES: { key: TensionStep; title: string; note: string }[] = [
  { key: 'score', title: 'Score', note: 'range check scored' },
]

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const answer = (option: string) => void api.operationInput(option).catch(fail)
const GOTO = 'goto:'

const previewUnavailable = (error: Error) => (
  <div className="gt-preview" title={error.message}>
    3D preview unavailable in this window — the steps still work.
  </div>
)

function fixedHolds(extra: GuidedTensionExtra): string {
  const fixed = Object.entries(extra.hold_fixed ?? {}).filter(([j]) => extra.stage?.joints.includes(j))
  return fixed.map(([j, ma]) => `, ${j.replace('_', ' ')} at ${ma} mA`).join('')
}

function pct(fraction: number | null | undefined): string {
  return fraction == null ? '—' : `${Math.round(fraction * 100)}%`
}

const deg = (value: number | null | undefined, digits = 0) =>
  value == null ? '—' : `${value.toFixed(digits)}°`

// Slack scoring: a latched motor shows what it is, not a number it cannot have
// earned; the others show the slack still in their tendons, in motor degrees.
function slackCell(motor: MotorSpread): string {
  if (motor.status === 'fault') return 'FAULT'
  if (motor.slack_deg == null) return 'n/a'
  return deg(Math.max(0, motor.slack_deg))
}

const clicksText = (clicks: number) => `~${clicks} click${clicks === 1 ? '' : 's'}`

// What the ratchet step says for a joint: the clicks its missing travel
// needs, or the travel itself while the degrees per click are unknown.
function todoCell(motor: MotorSpread, slack: boolean): string {
  if (motor.status === 'fault') return 'FAULT'
  if (motor.clicks_left != null) return motor.clicks_left > 0 ? clicksText(motor.clicks_left) : 'under 1 click'
  return slack ? `${deg(Math.max(0, motor.slack_deg ?? 0))} slack` : pct(motor.fraction)
}

// Thresholds the rows fall back on when a row carries none of its own.
interface Thresholds {
  slack: boolean
  passFraction: number
  passSlack: number
}

export function GuidedTensionDialog({
  operation,
  onClose,
}: {
  operation: OperationSnapshot
  onClose: () => void
}) {
  const handInfo = useAppStore((s) => s.handInfo)
  const caps = useAppStore((s) => s.status?.capabilities)
  const [metadata, setMetadata] = useState<ModelMetadata | null>(null)
  useEffect(() => {
    api.modelMetadata().then(setMetadata).catch(fail)
  }, [handInfo?.side])

  const extra = operation.extra as GuidedTensionExtra | null
  const active = isOperationActive(operation)
  const step: TensionStep | null = active ? (extra?.step ?? null) : 'done'
  const awaiting = operation.state === 'awaiting_input' ? operation.awaiting : null
  const slack = extra?.scoring === 'slack'
  const thresholds: Thresholds = {
    slack,
    passFraction: Math.min(...Object.values(extra?.pass_fractions ?? DEFAULT_PASS)),
    passSlack: Math.max(...Object.values(extra?.pass_slack_deg ?? DEFAULT_PASS_SLACK)),
  }
  // One answer per prompt: the buttons lock until the next prompt arrives.
  const promptKey = awaiting
    ? [awaiting.prompt, extra?.step, extra?.stage?.key, extra?.round, extra?.pulled_deg].join('|')
    : null
  const [sentFor, setSentFor] = useState<string | null>(null)
  const [confirmRestart, setConfirmRestart] = useState(false)

  // Stop this run, then start a fresh one with the same settings and no saved
  // progress: resume=false makes the backend drop the scores it kept.
  const restart = async () => {
    setConfirmRestart(false)
    const { defaults: _defaults, ...params } = (operation.params ?? {}) as Record<string, unknown>
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
    try {
      if (active) await api.operationStop()
      for (let i = 0; i < 100; i++) {
        const current = (await api.operation()).operation
        if (!current || !isOperationActive(current)) break
        await sleep(300)
      }
      let lastError: unknown = null
      for (let i = 0; i < 60; i++) {
        try {
          await api.operationStart('guided_tension', { ...params, resume: false })
          return
        } catch (error) {
          lastError = error   // the hand is still reconnecting after the stopped run
          await sleep(500)
        }
      }
      fail(lastError)
    } catch (error) {
      fail(error)
    }
  }
  const sent = promptKey !== null && sentFor === promptKey
  const send = (option: string) => {
    setSentFor(promptKey)
    answer(option)
  }

  useEffect(() => {
    if (!awaiting) return
    const onKey = (e: KeyboardEvent) => {
      if (sent) return
      // Fields take Enter themselves, and a focused button answers it.
      if (e.key === 'Enter' && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLButtonElement)) {
        e.preventDefault()
        send(awaiting.options[0])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const motors = extra?.motors ?? []
  const statusKey = motors.map((m) => `${m.joint}:${m.status}`).join(',')
  const statuses = useMemo(
    () => Object.fromEntries(motors.map((m) => [m.joint, m.status])) as Record<string, SpreadStatus>,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [statusKey],
  )

  const previewMode: PreviewMode = step === 'range' ? 'sweep' : step === 'pose' ? 'pose' : 'still'
  const stage = step === 'pose' || step === 'range' ? (extra?.stage ?? null) : null
  const preview =
    metadata && handInfo ? (
      <ErrorBoundary label="The hand preview" fallback={previewUnavailable}>
        <Suspense fallback={<div className="gt-preview">loading model…</div>}>
          <TensionPreview
            urdfUrl={metadata.urdf_url}
            joints={handInfo.joints}
            mode={previewMode}
            stage={stage}
            statuses={
              stage
                ? Object.fromEntries(Object.entries(statuses).filter(([j]) => stage.joints.includes(j)))
                : statuses
            }
            blackSkin={(handInfo.tactile_skin ?? caps?.declared?.tactile ?? caps?.tactile) === true}
          />
        </Suspense>
      </ErrorBoundary>
    ) : (
      <div className="gt-preview">loading model…</div>
    )

  // Sidebar: one entry per finger stage, then score and tension.
  const stages = extra?.stages ?? []
  const steps = [
    ...BEFORE_STAGES,
    ...stages.map((st) => ({ key: `stage:${st.key}`, title: st.title, note: 'pose, then move' })),
    ...AFTER_STAGES,
  ]
  const currentKey = stage ? `stage:${stage.key}` : step
  const buttons = awaiting?.options.filter((o) => !o.startsWith(GOTO)) ?? []
  const stepIndex = steps.findIndex((s) => s.key === currentKey)
  const keptBefore = motors.filter(
    (m) => m.kept != null && m.kept >= (m.pass_fraction ?? thresholds.passFraction),
  ).length

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Guided tensioning">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Guided tensioning</span>
          {extra && <span className="setup-badge">round {extra.round}</span>}
          {extra?.baseline && (
            <span
              className="setup-badge"
              title={
                extra.baseline.name
                  ? `Expected travel per joint from baseline ${extra.baseline.name} (${extra.baseline.source}, ${extra.baseline.joints ?? '?'} joints)`
                  : 'Expected travel per joint from the shared v2.1 block'
              }
            >
              vs {extra.baseline.source === 'reference' ? 'reference hand' : (extra.baseline.name ?? 'v2.1 shared')}
            </span>
          )}
          {extra?.resumed && !slack && (
            <span className="setup-badge" title="Joints that passed before stay passed">
              resumed · {keptBefore} passed before
            </span>
          )}
          {extra?.resumed && slack && (
            <span
              className="setup-badge"
              title="Every joint is checked again this round; the earlier rounds only count towards the total"
            >
              round {extra.resumed.rounds} before · {extra.resumed.passed ?? 0}/{extra.resumed.joints} passed then
            </span>
          )}
          <span className="gt-header-spacer" />
          {active ? (
            <>
              <button
                className="btn btn-secondary"
                title="Reset the rounds and every saved score, then start again"
                onClick={() => setConfirmRestart(true)}
              >
                Restart
              </button>
              <button className="btn btn-secondary" title="Keeps the run going" onClick={onClose}>
                Hide
              </button>
              <button className="btn btn-secondary" onClick={() => void api.operationStop().catch(fail)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="gt-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          )}
        </header>
        {confirmRestart && (
          <div className="gt-warning gt-confirm">
            <span>
              Are you sure you wish to reset the tensioning process fully to factory default and
              delete existing scores?
            </span>
            <button className="btn btn-danger" onClick={() => void restart()}>
              Reset
            </button>
            <button className="btn btn-secondary" onClick={() => setConfirmRestart(false)}>
              Keep going
            </button>
          </div>
        )}
        <div className="gt-body">
          <nav className="gt-steps">
            {steps.map((s, i) => {
              const jump = `${GOTO}${s.key.startsWith('stage:') ? s.key.slice(6) : s.key}`
              const canJump = awaiting?.options.includes(jump) ?? false
              return (
                <div
                  key={s.key}
                  className={`gt-step${i === stepIndex ? ' active' : i < stepIndex || step === 'done' ? ' done' : ''}${canJump ? ' jump' : ''}`}
                  role={canJump ? 'button' : undefined}
                  title={canJump ? `Go to ${s.title.toLowerCase()}` : undefined}
                  onClick={canJump && !sent ? () => send(jump) : undefined}
                >
                  <span className="gt-step-num">{i + 1}</span>
                  <span>
                    <div className="gt-step-title">{s.title}</div>
                    <div className="gt-step-note">
                      {i === stepIndex && step === 'pose' ? 'pose the hand · torque off'
                        : i === stepIndex && step === 'range' ? 'move · motors hold the pose'
                          : s.note}
                    </div>
                  </span>
                </div>
              )
            })}
            {extra && active && (
              <details className="gt-advanced">
                <summary className="gt-todo-title">Advanced settings</summary>
                <CurrentsEditor extra={extra} step={step} />
                <PassEditor extra={extra} step={step} />
              </details>
            )}
            {extra && extra.history.length > 0 && (
              <div className="gt-history">
                {extra.history.map((h) => (
                  <div key={h.round}>
                    round {h.round}: {h.passed}/{h.scored} · {pct(h.fraction)}
                  </div>
                ))}
              </div>
            )}
          </nav>
          <section className="gt-content">
            <StepContent
              operation={operation}
              extra={extra}
              step={step}
              preview={preview}
              thresholds={thresholds}
            />
            {awaiting && (
              <div className="gt-actions">
                {/* The Enter answer sits bottom right, where the eye ends up. */}
                {[...buttons.slice(1), buttons[0]].map((option) => {
                  const primary = option === awaiting.options[0]
                  return (
                    <button
                      key={option}
                      className={`btn ${primary ? 'btn-primary' : 'btn-secondary'}`}
                      disabled={sent}
                      onClick={() => send(option)}
                    >
                      {option === PULL_MORE
                        ? `Pull ${EXTRA_DEG}° more`
                        : option === 'Done' && step === 'tension'
                          ? `Round ${(extra?.round ?? 1) + 1}`
                          : option}
                      {primary && <span className="gt-key">↵</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function StepContent({
  operation,
  extra,
  step,
  preview,
  thresholds,
}: {
  operation: OperationSnapshot
  extra: GuidedTensionExtra | null
  step: TensionStep | null
  preview: ReactNode
  thresholds: Thresholds
}) {
  if (operation.state === 'error') {
    return (
      <div className="gt-pane">
        <h3 className="gt-heading">Stopped</h3>
        <p className="setup-copy">{operation.error ?? 'the run ended with an error'} — torque is off.</p>
      </div>
    )
  }
  if (!extra || step === null) {
    return (
      <div className="gt-pane">
        <h3 className="gt-heading">Taking over the hand…</h3>
        <p className="setup-copy">{operation.detail}</p>
      </div>
    )
  }
  const motors = extra.motors
  const { slack } = thresholds
  switch (step) {
    case 'pose':
      return (
        <div className="gt-split">
          {preview}
          <div className="gt-pane">
            <div className="gt-todo-title">
              Stage {(extra.stage_index ?? 0) + 1} of {extra.stage_count ?? 1} · {extra.stage?.title}
            </div>
            <h3 className="gt-heading">Pose your physical hand similarly to the 3d model</h3>
            <p className="setup-copy">
              Left clicking and dragging will allow you to rotate the model for a better view.
              Torque is currently off, you may move each joint freely.
            </p>
            <p className="setup-copy">{extra.stage?.pose}</p>
            <p className="setup-copy">
              Pressing continue will enable torque, "freezing" this pose and beginning the next
              step in the tensioning process.
            </p>
          </div>
        </div>
      )
    case 'range': {
      const testing = new Set(extra.stage?.joints ?? [])
      return (
        <div className="gt-range">
          <div className="gt-range-top">
            {preview}
            <div className="gt-pane">
              <div className="gt-todo-title">
                Stage {(extra.stage_index ?? 0) + 1} of {extra.stage_count ?? 1} · {extra.stage?.title}
              </div>
              <h3 className="gt-heading">
                Move the {stageSubject(extra.stage)}, under tension, through{' '}
                {stagePossessive(extra.stage)} full range of motion
              </h3>
              {slack ? (
                <p className="setup-copy">
                  The motors hold this pose at {extra.hold_ap}/{extra.hold_mcp}/{extra.hold_pip} mA
                  (APs/MCPs/PIPs){fixedHolds(extra)}. Drive each highlighted joint by hand to both ends, one joint at a
                  time, like the model, and <b>hold each end still for a moment</b> — a fast flick
                  does not count, so the motor cannot overshoot its way to a pass. Reach each end
                  twice. A joint turns green once its sweep is within its tolerance
                  ({passTargets(extra)} of slack) and both ends were reached twice; it shows
                  "again" while an end has only been reached once. Orange means more than 30% of
                  the travel was swept. Press next after driving each joint as far as it goes.
                </p>
              ) : (
                <p className="setup-copy">
                  The motors hold this pose at {extra.hold_ap}/{extra.hold_mcp}/{extra.hold_pip} mA
                  (APs/MCPs/PIPs){fixedHolds(extra)}. Drive each highlighted joint by hand to both ends, one joint at a
                  time, like the model. You will have to apply a little force as the targeted joints
                  will be putting up some amount of resistance. A motor turns green once it has
                  followed its group's pass threshold ({passTargets(extra)}) of its travel; orange
                  past 30%. Do not
                  worry if you cannot hit the {Math.round(thresholds.passFraction * 100)} percent target on the
                  first round. Simply press next after driving each joint to the maximum possible
                  value.
                </p>
              )}
              <ScoreLine extra={extra} slack={slack} />
            </div>
          </div>
          <MotorGrid motors={motors} thresholds={thresholds} focus={testing} canRetest />
          <ExcludedNote excluded={extra.excluded} />
        </div>
      )
    }
    case 'score':
      return (
        <div className="gt-range">
          <div className="gt-score">
            <div className="gt-score-big">{pct(extra.fraction)}</div>
            <div>
              <ScoreLine extra={extra} slack={slack} />
              {slack ? (
                <p className="setup-copy">
                  {extra.passed === extra.scored
                    ? 'Every joint is within its slack tolerance and confirmed. Finish, then calibrate.'
                    : `Joints with more slack than their tolerance (${passTargets(extra)}) are listed in red and orange. ` +
                      'We will now tension them and then check every joint again.'}
                </p>
              ) : (
                <p className="setup-copy">
                  {extra.passed === extra.scored
                    ? 'Every motor follows its joint. Finish, then calibrate.'
                    : `Joints under the tensioning target (${passTargets(extra)}) still have slack. ` +
                      'We will now tension them and then proceed to the next round.'}
                </p>
              )}
              {slack && motors.some((m) => m.status === 'unconfirmed') && (
                <p className="setup-copy">
                  Joints marked "again" are within tolerance but one end was reached only once;
                  they need no ratchet, just a repeated sweep next round.
                </p>
              )}
            </div>
          </div>
          <MotorGrid motors={motors} thresholds={thresholds} canRetest />
          <ExcludedNote excluded={extra.excluded} />
        </div>
      )
    case 'tension': {
      // From the sweep the run was opened with, or from this round's score;
      // each listed spool carries its clicks on the tower.
      const motorOf = Object.fromEntries(motors.map((m) => [m.joint, m.motor]))
      const marks = extra.ratchet
        ? Object.entries(extra.ratchet).map(([joint, r]) => ({
            joint,
            motor: motorOf[joint] ?? 0,
            status: ((r.pct ?? 0) < 70 ? 'low' : 'partial') as SpreadStatus,
            fraction: null,
            tag: r.clicks ? clicksText(r.clicks) : 'under 1 click',
          }))
        : motors.map((m) => ({
            joint: m.joint,
            motor: m.motor,
            status: m.status,
            fraction: m.fraction,
            tag: ['pass', 'unconfirmed', 'unscored'].includes(m.status) ? undefined : todoCell(m, slack),
          }))
      return (
        <div className="gt-tension">
          <div className="gt-pane">
            <h3 className="gt-heading">Now use the ratchet tool</h3>
            <p className="setup-copy">
              Hulls off. The finger motors have slowly turned {extra.pulled_deg ?? extra.tension_offset_deg}°
              counterclockwise and are holding with {extra.tension_current} mA of current, the rotation should have
              placed some tension on all tendons attached to the bottom spools. If any bottom spool tendons still feel
              loose, press "{PULL_MORE}" ({EXTRA_DEG}° more).
            </p>
            <p className="setup-copy">
              Turn the top spool of each marked motor by the clicks shown next to it. The counts are rounded down on
              purpose: stay a little loose here — the tension sweep after calibration counts the last clicks.
              {extra.deg_per_click == null &&
                ' The degrees one click takes up are not set yet, so the spools show the missing travel instead.'}
            </p>
          </div>
          <ErrorBoundary label="The tower preview" fallback={previewUnavailable}>
            <TowerFaces withList={false} tags="full" marks={marks} head={[]} columns="" row={() => []} />
          </ErrorBoundary>
          <div className="gt-warning">
            Tension carefully. Stop as soon as the tendon feels firm — overtensioning makes the joint stall short of
            its range and wears the motor.
          </div>
        </div>
      )
    }
    case 'done':
      if (!extra.completed && operation.result == null) {
        return (
          <div className="gt-pane">
            <h3 className="gt-heading">Cancelled</h3>
            <p className="setup-copy">Torque is off. Nothing was recorded — calibrate before use.</p>
          </div>
        )
      }
      return (
        <div className="gt-range">
          <div className="gt-score">
            <div className="gt-score-big">{pct(extra.fraction)}</div>
            <div>
              <h3 className="gt-heading">
                {extra.completed ? 'Tensioning complete' : 'Finished below 100%'}
              </h3>
              <p className="setup-copy">
                {extra.completed
                  ? 'Saved as this hand’s last successful tension. Next: calibrate, then the tension sweep counts the clicks still missing.'
                  : 'Not recorded as a successful tension. Calibrate (Calibrate step), then run the tension sweep.'}
              </p>
            </div>
          </div>
          {motors.length > 0 && <MotorGrid motors={motors} thresholds={thresholds} />}
        </div>
      )
  }
}

// The thumb is "the thumb"; any other stage is one finger.
function stageSubject(stage?: RangeStage): string {
  if (!stage) return 'joints'
  const title = stage.title.toLowerCase()
  return title === 'thumb' ? title : `${title} finger`
}

function stagePossessive(stage?: RangeStage): string {
  return stage && stage.title.toLowerCase().includes(' and ') ? 'their' : 'its'
}

// The pass target per joint group: "80% APs / 80% MCPs / 80% PIPs" under
// fraction scoring, "3° APs / 5° MCPs / 5° PIPs" of slack under slack scoring.
function passTargets(extra: GuidedTensionExtra): string {
  if (extra.scoring === 'slack') {
    const p = extra.pass_slack_deg
    const show = (v: number | undefined, key: keyof PassSlack) => `${v ?? DEFAULT_PASS_SLACK[key]}°`
    return `${show(p?.ap, 'ap')} APs / ${show(p?.mcp, 'mcp')} MCPs / ${show(p?.pip, 'pip')} PIPs`
  }
  const p = extra.pass_fractions
  const show = (f: number | undefined) => `${Math.round((f ?? DEFAULT_PASS.ap) * 100)}%`
  return `${show(p?.ap)} APs / ${show(p?.mcp)} MCPs / ${show(p?.pip)} PIPs`
}

function ScoreLine({ extra, slack }: { extra: GuidedTensionExtra; slack: boolean }) {
  return (
    <div className="gt-scoreline">
      <b>
        {extra.passed ?? 0}/{extra.scored ?? 0}
      </b>{' '}
      {slack ? 'joints within tolerance' : 'motors at full travel'}
    </div>
  )
}

// Joints the run left out, with the reason: nobody should wonder where a finger went.
function ExcludedNote({ excluded }: { excluded?: GuidedTensionExtra['excluded'] }) {
  if (!excluded || excluded.length === 0) return null
  const reasons = new Map<string, string[]>()
  for (const e of excluded) reasons.set(e.reason, [...(reasons.get(e.reason) ?? []), e.joint])
  return (
    <div className="flow-info warn gt-excluded">
      {[...reasons.entries()].map(([reason, joints]) => (
        <div key={reason}>
          not scored — {reason}: {joints.join(', ')}
        </div>
      ))}
    </div>
  )
}

function MotorGrid({
  motors,
  thresholds,
  focus,
  canRetest = false,
}: {
  motors: MotorSpread[]
  thresholds: Thresholds
  focus?: Set<string>
  // A passed row gets a button that drops its pass so it is tested again.
  canRetest?: boolean
}) {
  // The stage's joints first; the rest stay visible but dimmed.
  const ordered = focus
    ? [...motors.filter((m) => focus.has(m.joint)), ...motors.filter((m) => !focus.has(m.joint))]
    : motors
  const Row = thresholds.slack ? SlackRow : FractionRow
  return (
    <div className="gt-grid">
      {ordered.map((m) => (
        <Row
          key={m.joint}
          motor={m}
          thresholds={thresholds}
          dim={focus !== undefined && !focus.has(m.joint)}
          canRetest={canRetest}
        />
      ))}
    </div>
  )
}

interface RowProps {
  motor: MotorSpread
  thresholds: Thresholds
  dim?: boolean
  canRetest?: boolean
}

// The last cell of a row: on a passed joint, a button that drops the pass so
// the range check scores it again; empty otherwise, so the columns line up.
function RetestCell({ motor, canRetest }: { motor: MotorSpread; canRetest?: boolean }) {
  if (!canRetest || (motor.status !== 'pass' && motor.status !== 'unconfirmed')) return <span />
  return (
    <button
      className="gt-retest"
      title={`Test ${motor.joint.replace('_', ' ')} again: drop its pass and sweep it once more`}
      onClick={() => answer(`again:${motor.joint}`)}
    >
      ↺
    </button>
  )
}

// Fraction scoring: percent of the expected travel, the pass band on the track.
function FractionRow({ motor, thresholds, dim = false, canRetest }: RowProps) {
  const passFraction = motor.pass_fraction ?? thresholds.passFraction
  // Passing on an earlier score rather than this check's movement.
  const keptPass =
    motor.kept != null && motor.kept >= passFraction && (motor.live_fraction ?? 0) < passFraction
  // Track spans one full travel centred on the hold position.
  const half = (motor.expected_deg ?? 1) / 2
  const at = (deg: number) => `${50 + Math.max(-50, Math.min(50, (deg / half) * 50))}%`
  return (
    <div className={`gt-row ${motor.status}${dim ? ' dim' : ''}`} title={`${motor.spread_deg.toFixed(0)}° of ${motor.expected_deg ?? '?'}°`}>
      <span className="gt-row-id">M{motor.motor}</span>
      <span className="gt-row-joint">
        {motor.joint}
        {keptPass && <em className="gt-kept"> kept</em>}
      </span>
      <span className="gt-track">
        {motor.expected_deg != null && (
          <>
            <span className="gt-track-goal" style={{ left: at(-half * passFraction), right: `calc(100% - ${at(half * passFraction)})` }} />
            <span className="gt-track-fill" style={{ left: at(motor.minus_deg), right: `calc(100% - ${at(motor.plus_deg)})` }} />
            <span className="gt-track-centre" />
            <span className="gt-track-now" style={{ left: at(motor.offset_deg) }} />
          </>
        )}
      </span>
      <span className="gt-row-pct">
        {motor.status === 'fault' ? 'FAULT' : motor.expected_deg == null ? 'n/a' : pct(motor.fraction)}
        {motor.status !== 'fault' && <small>/{Math.round(passFraction * 100)}</small>}
      </span>
      <RetestCell motor={motor} canRetest={canRetest} />
    </div>
  )
}

// Slack scoring: slack in motor degrees, the goal band is the travel less the
// tolerance, and the ends reached so far.
function SlackRow({ motor, thresholds, dim = false, canRetest }: RowProps) {
  const tolerance = motor.pass_slack_deg ?? thresholds.passSlack
  const half = (motor.expected_deg ?? 1) / 2
  const goal = Math.max(0, half - tolerance / 2)
  const at = (deg: number) => `${50 + Math.max(-50, Math.min(50, (deg / half) * 50))}%`
  const ends = `${motor.plus_hits}/${motor.minus_hits}`
  const title =
    `${motor.spread_deg.toFixed(0)}° swept of ${motor.expected_deg ?? '?'}° · slack ${deg(motor.slack_deg)} ` +
    `(tolerance ${tolerance}°) · ends reached +${motor.plus_hits} / −${motor.minus_hits}`
  return (
    <div className={`gt-row ${motor.status}${dim ? ' dim' : ''}`} title={title}>
      <span className="gt-row-id">M{motor.motor}</span>
      <span className="gt-row-joint">
        {motor.joint}
        {motor.status === 'unconfirmed' && <em className="gt-again"> again</em>}
      </span>
      <span className="gt-track">
        {motor.expected_deg != null && (
          <>
            <span className="gt-track-goal" style={{ left: at(-goal), right: `calc(100% - ${at(goal)})` }} />
            <span className="gt-track-fill" style={{ left: at(motor.minus_deg), right: `calc(100% - ${at(motor.plus_deg)})` }} />
            <span className="gt-track-centre" />
            <span className="gt-track-now" style={{ left: at(motor.offset_deg) }} />
          </>
        )}
      </span>
      <span className="gt-row-pct">
        {slackCell(motor)}
        {motor.status !== 'fault' && motor.slack_deg != null && (
          <small title="ends reached: + / −">/{tolerance}° · {ends}</small>
        )}
      </span>
      <RetestCell motor={motor} canRetest={canRetest} />
    </div>
  )
}

const CURRENT_FIELDS = [
  { key: 'hold_ap', label: 'Hold · APs', step: 'range', min: 20, max: 500, unit: 'mA', inc: 10 },
  { key: 'hold_mcp', label: 'Hold · MCPs', step: 'range', min: 20, max: 500, unit: 'mA', inc: 10 },
  { key: 'hold_pip', label: 'Hold · PIPs', step: 'range', min: 20, max: 500, unit: 'mA', inc: 10 },
  { key: 'tension_current', label: 'Tensioning', step: 'tension', min: 50, max: 1000, unit: 'mA', inc: 10 },
  { key: 'tension_offset_deg', label: 'Turn CCW', step: null, min: 0, max: 45, unit: '°', inc: 5 },
] as const

// Changes apply to the next step that uses the current, and at once when that
// step is the one running (the pull applies from the next tension step).
function CurrentsEditor({ extra, step }: { extra: GuidedTensionExtra; step: TensionStep | null }) {
  return (
    <div className="gt-currents">
      <div className="gt-todo-title">Currents</div>
      {CURRENT_FIELDS.map((f) => (
        <CurrentField
          key={f.key}
          label={f.label}
          live={step === f.step}
          value={extra[f.key] ?? 0}
          min={f.min}
          max={f.max}
          unit={f.unit}
          step={f.inc}
          onCommit={(v) => answer(`current:${f.key}=${v}`)}
        />
      ))}
    </div>
  )
}

function CurrentField({
  label,
  hint,
  unit = 'mA',
  live,
  value,
  min,
  max,
  step = 10,
  onCommit,
}: {
  label: string
  hint?: string
  unit?: string
  live: boolean
  value: number
  min: number
  max: number
  step?: number
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const parsed = Number(draft)
  const valid = draft !== '' && Number.isFinite(parsed) && parsed >= min && parsed <= max
  const commit = () => {
    if (valid && parsed !== value) onCommit(parsed)
    else setDraft(String(value))
  }
  return (
    <label className={`gt-current${live ? ' live' : ''}`} title={hint ?? `${min}–${max} ${unit}`}>
      <span>
        {label}
        {live && <em> · live</em>}
      </span>
      <span className="gt-setting-input">
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={draft}
          className={valid ? undefined : 'invalid'}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              e.stopPropagation()
              commit()
            }
          }}
        />
        {unit}
      </span>
    </label>
  )
}

// Pass thresholds per joint group: percent of each joint's travel (fraction
// scoring) or a slack tolerance in motor degrees (slack scoring). Live during
// the range check, otherwise from the next check.
function PassEditor({ extra, step }: { extra: GuidedTensionExtra; step: TensionStep | null }) {
  if (extra.scoring === 'slack') {
    const passes = extra.pass_slack_deg
    if (!passes) return null
    return (
      <div className="gt-currents">
        <div className="gt-todo-title">Slack tolerance</div>
        {PASS_GROUPS.map((g) => (
          <CurrentField
            key={g.key}
            label={g.label}
            hint={`${g.hint} · pass when the sweep falls short of the expected travel by at most this`}
            unit="°"
            live={step === 'range'}
            value={passes[g.key]}
            min={PASS_BOUNDS_DEG[0]}
            max={PASS_BOUNDS_DEG[1]}
            step={0.5}
            onCommit={(v) => {
              savePassSlack({ ...passes, [g.key]: v } as PassSlack)
              answer(`pass:${g.key}=${v}`)
            }}
          />
        ))}
      </div>
    )
  }
  const passes = extra.pass_fractions
  if (!passes) return null
  return (
    <div className="gt-currents">
      <div className="gt-todo-title">Pass at</div>
      {PASS_GROUPS.map((g) => (
        <CurrentField
          key={g.key}
          label={g.label}
          hint={g.hint}
          unit="%"
          live={step === 'range'}
          value={Math.round(passes[g.key] * 100)}
          min={PASS_BOUNDS_PCT[0]}
          max={PASS_BOUNDS_PCT[1]}
          step={5}
          onCommit={(v) => {
            savePassFractions({ ...passes, [g.key]: v / 100 } as PassFractions)
            answer(`pass:${g.key}=${v / 100}`)
          }}
        />
      ))}
    </div>
  )
}

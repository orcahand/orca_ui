// Guided tensioning as an installer-style dialog over the console. The
// operation drives the steps (centre → range check → score → tension, per
// round); this mirrors its snapshot and answers its prompts. Enter takes the
// primary answer. The dialog outlives the run until closed, so the final
// score stays readable.

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
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { isOperationActive } from '../../state/operationStore'
import { EXTRA_DEG, PULL_MORE } from '../../state/tensionFlow'
import type { PreviewMode } from './TensionPreview'
import {
  DEFAULT_PASS,
  PASS_BOUNDS_PCT,
  PASS_GROUPS,
  savePassFractions,
  type PassFractions,
} from './guidedSettings'

const TensionPreview = lazy(() =>
  import('./TensionPreview').then((m) => ({ default: m.TensionPreview })),
)
const TowerPreview = lazy(() =>
  import('./TowerPreview').then((m) => ({ default: m.TowerPreview })),
)

const AFTER_STAGES: { key: TensionStep; title: string; note: string }[] = [
  { key: 'score', title: 'Score', note: 'how many motors followed' },
  { key: 'tension', title: 'Tension', note: 'ratchet tool' },
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

function pct(fraction: number | null | undefined): string {
  return fraction == null ? '—' : `${Math.round(fraction * 100)}%`
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
  const passFraction = Math.min(...Object.values(extra?.pass_fractions ?? DEFAULT_PASS))
  // One answer per prompt: the buttons lock until the next prompt arrives.
  const promptKey = awaiting
    ? [awaiting.prompt, extra?.step, extra?.stage?.key, extra?.round, extra?.pulled_deg].join('|')
    : null
  const [sentFor, setSentFor] = useState<string | null>(null)
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
            blackSkin={(caps?.declared?.tactile ?? caps?.tactile) === true}
          />
        </Suspense>
      </ErrorBoundary>
    ) : (
      <div className="gt-preview">loading model…</div>
    )

  // Sidebar: one entry per finger stage, then score and tension.
  const stages = extra?.stages ?? []
  const steps = [
    ...stages.map((st) => ({ key: `stage:${st.key}`, title: st.title, note: 'pose, then move' })),
    ...AFTER_STAGES,
  ]
  const currentKey = stage ? `stage:${stage.key}` : step
  const buttons = awaiting?.options.filter((o) => !o.startsWith(GOTO)) ?? []
  const stepIndex = steps.findIndex((s) => s.key === currentKey)

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Guided tensioning">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Guided tensioning</span>
          {extra && <span className="setup-badge">round {extra.round}</span>}
          {extra?.resumed && (
            <span className="setup-badge" title="Joints that passed before stay passed">
              resumed ·{' '}
              {extra.motors.filter((m) => m.kept != null && m.kept >= (m.pass_fraction ?? DEFAULT_PASS.ap)).length}{' '}
              passed before
            </span>
          )}
          <span className="gt-header-spacer" />
          {active ? (
            <>
              <button className="btn btn-secondary" title="Keeps the run going" onClick={onClose}>
                Hide
              </button>
              <button className="btn btn-secondary" onClick={() => void api.operationStop().catch(fail)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="btn btn-secondary" onClick={onClose}>
              Close
            </button>
          )}
        </header>
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
            {extra && active && <CurrentsEditor extra={extra} step={step} />}
            {extra && active && <PassEditor extra={extra} step={step} />}
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
              passFraction={passFraction}
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
                      {option === PULL_MORE ? `Pull ${EXTRA_DEG}° more` : option}
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
  passFraction,
}: {
  operation: OperationSnapshot
  extra: GuidedTensionExtra | null
  step: TensionStep | null
  preview: ReactNode
  passFraction: number
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
  switch (step) {
    case 'pose':
      return (
        <div className="gt-split">
          {preview}
          <div className="gt-pane">
            <div className="gt-todo-title">
              Stage {(extra.stage_index ?? 0) + 1} of {extra.stage_count ?? 1} · {extra.stage?.title}
            </div>
            <h3 className="gt-heading">Pose the hand like the model</h3>
            <p className="setup-copy">Torque is off. {extra.stage?.pose}</p>
            <p className="setup-copy">
              Continue freezes this pose; then you move only the {extra.stage?.title.toLowerCase()}{' '}
              joints.
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
              <h3 className="gt-heading">Move the {extra.stage?.title.toLowerCase()} through their range</h3>
              <p className="setup-copy">
                The motors hold this pose at {extra.hold_ap}/{extra.hold_mcp}/{extra.hold_pip} mA
                (APs/MCPs/PIPs). Drive each highlighted joint by hand to both ends, one joint at a
                time, like the model. A motor turns green once it has followed its group's pass
                threshold (left) of its travel; orange past 30%.
              </p>
              <ScoreLine extra={extra} />
            </div>
          </div>
          <MotorGrid motors={motors} passFraction={passFraction} focus={testing} />
        </div>
      )
    }
    case 'score':
      return (
        <div className="gt-range">
          <div className="gt-score">
            <div className="gt-score-big">{pct(extra.fraction)}</div>
            <div>
              <ScoreLine extra={extra} />
              <p className="setup-copy">
                {extra.passed === extra.scored
                  ? 'Every motor follows its joint. Finish, then calibrate.'
                  : 'Highlighted joints still have slack. Tension them, then check again.'}
              </p>
            </div>
          </div>
          <MotorGrid motors={motors} passFraction={passFraction} />
        </div>
      )
    case 'tension': {
      const todo = motors
        .filter((m) => m.status !== 'pass' && m.status !== 'unscored')
        .sort((a, b) => (a.fraction ?? 0) - (b.fraction ?? 0))
      return (
        <div className="gt-tension">
          <ErrorBoundary label="The tower preview" fallback={previewUnavailable}>
            <Suspense fallback={<div className="gt-preview">loading tower…</div>}>
              <TowerPreview motors={motors} />
            </Suspense>
          </ErrorBoundary>
          <div className="gt-pane">
            <h3 className="gt-heading">Now use the ratchet tool</h3>
            <p className="setup-copy">
              Hulls off. The finger motors have slowly turned{' '}
              {extra.pulled_deg ?? extra.tension_offset_deg}° counterclockwise and hold at{' '}
              {extra.tension_current} mA, loading the bottom spools. Turn the spool of each
              coloured motor clockwise to take up the slack — red first, then orange. Not enough
              load? Pull {EXTRA_DEG}° more.
            </p>
            <div className="gt-warning">
              Tension carefully. Stop as soon as the tendon feels firm — overtensioning makes the
              joint stall short of its range and wears the motor.
            </div>
            <div className="gt-todo">
              <div className="gt-todo-title">
                Still to tension · {todo.length}
              </div>
              {todo.map((m) => (
                <div key={m.joint} className={`gt-todo-row ${m.status}`}>
                  <b>M{m.motor}</b>
                  <span>{m.joint}</span>
                  <span>{pct(m.fraction)}</span>
                </div>
              ))}
            </div>
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
                  ? 'Saved as this hand’s last successful tension. Calibrate next — tensioning changes the tendon lengths.'
                  : 'Not recorded as a successful tension. Calibrate before use.'}
              </p>
            </div>
          </div>
          {motors.length > 0 && <MotorGrid motors={motors} passFraction={passFraction} />}
        </div>
      )
  }
}

function ScoreLine({ extra }: { extra: GuidedTensionExtra }) {
  return (
    <div className="gt-scoreline">
      <b>
        {extra.passed ?? 0}/{extra.scored ?? 0}
      </b>{' '}
      motors at full travel
    </div>
  )
}

function MotorGrid({
  motors,
  passFraction,
  focus,
}: {
  motors: MotorSpread[]
  passFraction: number
  focus?: Set<string>
}) {
  // The stage's joints first; the rest stay visible but dimmed.
  const ordered = focus
    ? [...motors.filter((m) => focus.has(m.joint)), ...motors.filter((m) => !focus.has(m.joint))]
    : motors
  return (
    <div className="gt-grid">
      {ordered.map((m) => (
        <MotorRow
          key={m.joint}
          motor={m}
          passFraction={passFraction}
          dim={focus !== undefined && !focus.has(m.joint)}
        />
      ))}
    </div>
  )
}

function MotorRow({
  motor,
  passFraction: fallback,
  dim = false,
}: {
  motor: MotorSpread
  passFraction: number
  dim?: boolean
}) {
  const passFraction = motor.pass_fraction ?? fallback
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
        {motor.expected_deg == null ? 'n/a' : pct(motor.fraction)}
        <small>/{Math.round(passFraction * 100)}</small>
      </span>
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

// Pass thresholds per joint group, in percent of each joint's travel: live
// during the range check, otherwise from the next check.
function PassEditor({ extra, step }: { extra: GuidedTensionExtra; step: TensionStep | null }) {
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

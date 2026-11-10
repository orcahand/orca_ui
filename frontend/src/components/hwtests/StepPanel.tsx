// The selected step: what to do and how it passes, its action and live
// readings, the decision with a note, screenshots, and what its check found.
// This element is what the screenshot button renders.

import { useRef, useState } from 'react'
import type { HwDecision, HwSession } from '../../api/hardwareTests'
import { hwApi } from '../../api/hardwareTests'
import {
  isHandsOn,
  undecidedHandsOn,
  useHardwareTestsStore,
  type HwStepRef,
} from '../../state/hardwareTestsStore'
import { CheckResultView } from './CheckResultView'
import { appliesToText, formatTime } from './hwFormat'
import { CopyPath, KindChip, StatusChip } from './hwShared'
import { LivePanels } from './LivePanels'
import { ScreenshotButton } from './ScreenshotButton'
import { StepActions } from './StepActions'

const DECISION_LABEL: Record<HwDecision, string> = {
  pass: 'Pass',
  fail: 'Fail',
  observed: 'Observed',
  skipped: 'Skip',
}

const DECISION_CLASS: Record<HwDecision, string> = {
  pass: 'btn-info',
  fail: 'btn-danger',
  observed: 'btn-scan',
  skipped: 'btn-secondary',
}

function decisionsFor(ref: HwStepRef): HwDecision[] {
  const { step } = ref
  if (!step.applicable || !isHandsOn(step)) return ['skipped']
  if (step.kind === 'observe') return ['observed', 'skipped']
  return ['pass', 'fail', 'observed', 'skipped']
}

export function StepPanel({ stepRef, session }: { stepRef: HwStepRef; session: HwSession }) {
  const { step, feature } = stepRef
  const result = step.result
  const panelRef = useRef<HTMLDivElement>(null)
  const [note, setNote] = useState(result.note)
  const busy = useHardwareTestsStore((s) => s.busy)
  const decide = useHardwareTestsStore((s) => s.decide)
  const runAuto = useHardwareTestsStore((s) => s.runAuto)
  const closeOpen = useHardwareTestsStore((s) => s.closeOpen)
  const refresh = useHardwareTestsStore((s) => s.refresh)

  const handsOn = isHandsOn(step)
  const open = session.open_step === step.id
  const autoBusy = session.auto.state !== 'idle'
  const blockedBy = undecidedHandsOn(session).length
  const params = Object.entries(step.params ?? {})
  const stepFolder = step.folder ?? `${feature.folder}/${step.id}`
  const verifying = step.verifying === true

  const reopen = () =>
    void hwApi
      .openStep(step.id)
      .then(() => refresh())
      .catch(() => undefined)

  return (
    <section
      ref={panelRef}
      className={`panel hwt-step-panel${step.applicable ? '' : ' hwt-not-applicable'}`}
    >
      <div className="hwt-step-head">
        <div>
          <div className="hwt-feature-line">
            {feature.title} <span className="hwt-dim">· {feature.group}</span>
          </div>
          <h2 className="hwt-step-title">
            <span className="hwt-step-id">{step.id}</span> {step.title}
          </h2>
        </div>
        <div className="hwt-step-chips">
          <KindChip kind={step.kind} />
          <StatusChip status={result.status} />
          {result.decided_by && <span className="hwt-dim">by {result.decided_by}</span>}
        </div>
      </div>

      <div className="hwt-meta">
        <span>applies to: {appliesToText(step.applies_to)}</span>
        {step.check && <span>check: {step.check}</span>}
        {result.started_at && <span>started {formatTime(result.started_at)}</span>}
        {result.finished_at && <span>finished {formatTime(result.finished_at)}</span>}
        <span>
          hand: {session.hand.label}
          {session.hand.mock ? ' (mock)' : ''}
        </span>
      </div>

      {!step.applicable && (
        <div className="hwt-na-box">
          Not applicable to this hand: {step.not_applicable_reason ?? 'no reason given'}
        </div>
      )}

      {handsOn && step.applicable && (
        <div className={`hwt-recording${open ? ' on' : ''}`}>
          {open ? (
            <>
              <span className="hwt-rec-dot" /> recording live readings into the step folder
              <button className="btn btn-secondary hwt-no-shot" onClick={() => void closeOpen()}>
                Stop recording
              </button>
            </>
          ) : (
            <>
              not recording
              <button className="btn btn-secondary hwt-no-shot" onClick={reopen}>
                Record readings
              </button>
            </>
          )}
        </div>
      )}

      <div className="hwt-block">
        <div className="hwt-label">Instructions</div>
        <div className="hwt-text">{step.instructions}</div>
      </div>
      <div className="hwt-block">
        <div className="hwt-label">Pass rule</div>
        <div className="hwt-text">{step.pass_rule}</div>
      </div>
      {params.length > 0 && (
        <div className="hwt-meta">
          {params.map(([key, value]) => (
            <span key={key}>
              {key}: {JSON.stringify(value)}
            </span>
          ))}
        </div>
      )}

      {step.applicable && handsOn && step.action && (
        <div className="hwt-block">
          <div className="hwt-label">Action</div>
          <StepActions action={step.action} />
        </div>
      )}

      {step.applicable && !handsOn && (
        <div className="hwt-block">
          <button
            className="btn btn-primary"
            disabled={busy || autoBusy}
            title={autoBusy ? 'the automatic run is busy' : undefined}
            onClick={() => void runAuto({ stepIds: [step.id], force: blockedBy > 0 })}
          >
            {blockedBy > 0 ? 'Run this check anyway' : 'Run this check'}
          </button>
          {blockedBy > 0 && (
            <span className="hwt-hint warn">
              {blockedBy} hands-on step{blockedBy === 1 ? ' is' : 's are'} still undecided
            </span>
          )}
        </div>
      )}

      {step.panels.length > 0 && step.applicable && (
        <div className="hwt-block">
          <div className="hwt-label">Live readings</div>
          <LivePanels panels={step.panels} />
        </div>
      )}

      {step.applicable && handsOn && step.check && (
        <div className="hwt-hint">
          After your decision the check “{step.check}” verifies it; a failing verification turns a
          pass into a fail and says why.
        </div>
      )}

      <div className="hwt-block">
        <div className="hwt-label">Decision</div>
        <textarea
          className="hwt-note"
          placeholder="note (what you saw, anything unexpected)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {result.note && result.note !== note && (
          <div className="hwt-hint">saved note: {result.note}</div>
        )}
        <div className="hwt-decisions">
          {decisionsFor(stepRef).map((status) => (
            <button
              key={status}
              className={`btn ${DECISION_CLASS[status]}${result.status === status ? ' hwt-chosen' : ''}`}
              disabled={busy || verifying || result.status === 'running'}
              title={verifying ? 'the check is still verifying the last decision' : undefined}
              onClick={() => void decide(step.id, status, note)}
            >
              {DECISION_LABEL[status]}
            </button>
          ))}
          <ScreenshotButton stepId={step.id} target={panelRef} />
        </div>
      </div>

      {result.screenshots.length > 0 && (
        <div className="hwt-block">
          <div className="hwt-label">Screenshots</div>
          <div className="hwt-shots">
            {result.screenshots.map((file) => (
              <code key={file}>screenshots/{file}</code>
            ))}
          </div>
        </div>
      )}

      {result.check && (
        <div className="hwt-block">
          <div className="hwt-label">Check result</div>
          <CheckResultView
            check={result.check}
            compare={step.kind === 'compare'}
            session={session}
          />
        </div>
      )}
      {(verifying || (result.status === 'running' && !result.check)) && (
        <div className="hwt-hint">
          {verifying
            ? `the check “${step.check}” is verifying your decision…`
            : 'the check is running…'}
        </div>
      )}

      <CopyPath label="step folder" path={stepFolder} />
    </section>
  )
}

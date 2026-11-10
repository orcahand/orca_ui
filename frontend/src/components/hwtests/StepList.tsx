// Rows of steps with their status colour; clicking one opens its panel.

import type { HwSession } from '../../api/hardwareTests'
import { useHardwareTestsStore, type HwStepRef } from '../../state/hardwareTestsStore'
import { KindChip, StatusChip } from './hwShared'

export function StepList({
  steps,
  session,
  empty,
}: {
  steps: HwStepRef[]
  session: HwSession
  empty: string
}) {
  const selected = useHardwareTestsStore((s) => s.selected)
  const select = useHardwareTestsStore((s) => s.select)
  if (steps.length === 0) return <div className="panel-empty">{empty}</div>

  return (
    <div className="hwt-steps">
      {steps.map(({ step, feature }) => {
        const result = step.result
        const current = session.auto.current_step === step.id
        const classes = [
          'hwt-step-row',
          `hwt-row-${result.status}`,
          selected === step.id ? 'selected' : '',
          step.applicable ? '' : 'hwt-not-applicable',
          current ? 'current' : '',
        ]
        return (
          <button
            key={step.id}
            className={classes.filter(Boolean).join(' ')}
            onClick={() => void select(step.id)}
            title={step.applicable ? step.instructions : (step.not_applicable_reason ?? undefined)}
          >
            <StatusChip status={result.status} muted={!step.applicable} />
            <span className="hwt-step-id">{step.id}</span>
            <span className="hwt-row-main">
              <span className="hwt-row-title">{step.title}</span>
              <span className="hwt-row-sub">
                {feature.title}
                {!step.applicable && ` · not applicable: ${step.not_applicable_reason ?? '—'}`}
                {step.applicable && result.check?.summary && ` · ${result.check.summary}`}
                {step.applicable && !result.check && result.note && ` · “${result.note}”`}
              </span>
            </span>
            <span className="hwt-row-tags">
              {session.open_step === step.id && <span className="hwt-rec">● rec</span>}
              {current && <span className="hwt-rec">▶ now</span>}
              {step.verifying && <span className="hwt-dim">verifying…</span>}
              {result.screenshots.length > 0 && (
                <span className="hwt-dim">
                  {result.screenshots.length} shot{result.screenshots.length === 1 ? '' : 's'}
                </span>
              )}
              <KindChip kind={step.kind} />
            </span>
          </button>
        )
      })}
    </div>
  )
}

// "3/8 decided · 1 fail · 2 not applicable"
export function StepCounts({ steps }: { steps: HwStepRef[] }) {
  const applicable = steps.filter(({ step }) => step.applicable)
  const count = (status: string) =>
    applicable.filter(({ step }) => step.result.status === status).length
  const done = applicable.filter(({ step }) =>
    ['pass', 'fail', 'observed', 'skipped', 'error'].includes(step.result.status),
  ).length
  const parts = [`${done}/${applicable.length} done`]
  for (const status of ['pass', 'fail', 'error', 'observed', 'skipped', 'running']) {
    const n = count(status)
    if (n > 0) parts.push(`${n} ${status}`)
  }
  const na = steps.length - applicable.length
  if (na > 0) parts.push(`${na} not applicable`)
  return <span className="hwt-counts">{parts.join(' · ')}</span>
}

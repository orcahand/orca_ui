// The automatic run: which checks it covers, which orca_core sides are
// available, Run / Stop, progress, the live log and each step's result as it lands.

import { useEffect, useRef } from 'react'
import type { HwSession, HwSideName } from '../../api/hardwareTests'
import { useAppStore } from '../../state/appStore'
import {
  undecidedHandsOn,
  useHardwareTestsStore,
  type HwStepRef,
} from '../../state/hardwareTestsStore'
import { Panel } from '../common/Panel'
import { StepCounts, StepList } from './StepList'

const LOG_LINES = 200

function SideBadge({ name, session }: { name: HwSideName; session: HwSession }) {
  const side = session.sides[name]
  const available = side?.available ?? false
  return (
    <div className={`hwt-side hwt-side-${name}${available ? '' : ' hwt-side-off'}`}>
      <div className="hwt-side-name">
        {name} <span className="hwt-dim">{available ? 'available' : 'unavailable'}</span>
      </div>
      {side?.version && <div className="hwt-side-version">{side.version}</div>}
      {!available && <div className="hwt-hint warn">{side?.reason ?? 'no reason given'}</div>}
    </div>
  )
}

function AutoLog({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLPreElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    const pane = ref.current
    if (pane && stick.current) pane.scrollTop = pane.scrollHeight
  }, [lines])
  if (lines.length === 0) return <div className="panel-empty">no log lines yet</div>
  return (
    <pre
      ref={ref}
      className="hwt-log"
      onScroll={(e) => {
        const pane = e.currentTarget
        stick.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 24
      }}
    >
      {lines.slice(-LOG_LINES).join('\n')}
    </pre>
  )
}

export function AutoCard({ steps, session }: { steps: HwStepRef[]; session: HwSession }) {
  const busy = useHardwareTestsStore((s) => s.busy)
  const runAuto = useHardwareTestsStore((s) => s.runAuto)
  const stopAuto = useHardwareTestsStore((s) => s.stopAuto)
  const handState = useAppStore((s) => s.status?.state ?? null)
  const auto = session.auto
  const running = auto.state !== 'idle'
  const undecided = undecidedHandsOn(session)
  const runnable = steps.filter(({ step }) => step.applicable)
  const compares = runnable.filter(({ step }) => step.kind === 'compare').length
  const sidesMissing = (['main', 'branch'] as const).filter((n) => !session.sides[n]?.available)
  const current = steps.find(({ step }) => step.id === auto.current_step)
  const pct = Math.round(Math.max(0, Math.min(1, auto.progress)) * 100)

  const blockReason =
    undecided.length > 0
      ? `Decide the hands-on steps first: ${undecided.map(({ step }) => step.id).join(', ')} still undecided.`
      : null

  return (
    <Panel title="Automatic checks" toolbar={<StepCounts steps={steps} />}>
      <div className="hwt-sides">
        <SideBadge name="main" session={session} />
        <SideBadge name="branch" session={session} />
      </div>
      <div className="hwt-meta">
        <span>
          {runnable.length} of {steps.length} checks apply to this hand
        </span>
        {compares > 0 && <span>{compares} compare main with branch</span>}
        {compares > 0 && sidesMissing.length > 0 && (
          <span className="hwt-hint warn">
            {sidesMissing.join(' and ')} unavailable: compare steps will not get both sides
          </span>
        )}
      </div>

      <div className="hwt-run-row">
        {running ? (
          <button
            className="btn btn-danger"
            disabled={busy || auto.state === 'stopping'}
            onClick={() => void stopAuto()}
          >
            {auto.state === 'stopping' ? 'Stopping…' : 'Stop'}
          </button>
        ) : (
          <>
            <button
              className="btn btn-primary"
              disabled={busy || blockReason !== null || runnable.length === 0}
              title={blockReason ?? undefined}
              onClick={() => void runAuto()}
            >
              Run automatic checks
            </button>
            {blockReason && (
              <button
                className="btn btn-danger"
                disabled={busy || runnable.length === 0}
                title="Runs the checks although hands-on steps are undecided; the run is recorded as forced."
                onClick={() => void runAuto({ force: true })}
              >
                Run anyway
              </button>
            )}
          </>
        )}
        <span className={`hwt-auto-state hwt-auto-${auto.state}`}>{auto.state}</span>
        {handState && handState !== 'connected' && (
          <span className="hwt-hint warn">
            hand {handState}
            {running ? ' (compare checks release it while main and branch run)' : ''}
          </span>
        )}
      </div>
      {blockReason && !running && <div className="hwt-hint warn">{blockReason}</div>}

      {(running || pct > 0) && (
        <div className="hwt-progress">
          <div className="hwt-progress-bar">
            <div className="hwt-progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <span>{pct}%</span>
          {current && (
            <span>
              <strong>{current.step.id}</strong> {current.step.title}
            </span>
          )}
          {auto.detail && <span className="hwt-dim">{auto.detail}</span>}
        </div>
      )}

      <StepList steps={steps} session={session} empty="This plan has no automatic checks." />

      <details className="hwt-details" open={running || auto.log.length > 0}>
        <summary>Run log ({auto.log.length} lines)</summary>
        <AutoLog lines={auto.log} />
      </details>
    </Panel>
  )
}

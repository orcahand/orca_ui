// The start card (plan, hand label) and, once a session runs, its header:
// the hand under test, both orca_core sides, progress and the paths on disk.

import { useState } from 'react'
import type { HwPlanSummary, HwSession } from '../../api/hardwareTests'
import { useAppStore } from '../../state/appStore'
import { allSteps, useHardwareTestsStore } from '../../state/hardwareTestsStore'
import { Panel } from '../common/Panel'
import { formatHardwareVersion, formatTime } from './hwFormat'
import { CopyPath } from './hwShared'
import { StepCounts } from './StepList'

function fallbackLabel(serial: string | null | undefined, side: string | null | undefined): string {
  if (serial) return serial
  const date = new Date().toISOString().slice(0, 10)
  return `unlabeled-${side || 'hand'}-${date}`
}

export function StartCard({ plans }: { plans: HwPlanSummary[] }) {
  const serial = useAppStore((s) => s.handInfo?.hand_id ?? null)
  const side = useAppStore((s) => s.status?.side || s.handInfo?.side || null)
  const model = useAppStore((s) => s.status?.model || s.handInfo?.model_name || null)
  const backendLabel = useHardwareTestsStore((s) => s.defaultLabel)
  const benchDir = useHardwareTestsStore((s) => s.benchDir)
  const busy = useHardwareTestsStore((s) => s.busy)
  const startSession = useHardwareTestsStore((s) => s.startSession)
  const [planId, setPlanId] = useState(plans[0]?.id ?? '')
  const [label, setLabel] = useState<string | null>(null)
  const shownLabel = label ?? backendLabel ?? fallbackLabel(serial, side)
  const plan = plans.find((p) => p.id === planId) ?? plans[0]

  return (
    <Panel title="Start a test session">
      <div className="hwt-form">
        <label>
          <span className="hwt-label">Plan</span>
          <select value={plan?.id ?? ''} onChange={(e) => setPlanId(e.target.value)}>
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        {plan && <div className="hwt-text">{plan.summary}</div>}
        <label>
          <span className="hwt-label">Hand label</span>
          <input
            type="text"
            value={shownLabel}
            onChange={(e) => setLabel(e.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="hwt-hint">
          {serial ? 'From the board serial.' : 'No board serial known: edit the label if you like.'}{' '}
          Hand: {model ?? 'unknown model'}
          {side ? ` · ${side}` : ''}. Results go to the bench folder under this label. Starting with
          the same plan and label as an unfinished session resumes it.
        </div>
        {benchDir && <CopyPath label="bench" path={`${benchDir}/${shownLabel.trim()}/tests`} />}
        <div>
          <button
            className="btn btn-primary"
            disabled={busy || !plan || shownLabel.trim() === ''}
            onClick={() => plan && void startSession(plan.id, shownLabel.trim())}
          >
            Start or resume
          </button>
        </div>
      </div>
    </Panel>
  )
}

export function SessionCard({ session }: { session: HwSession }) {
  const busy = useHardwareTestsStore((s) => s.busy)
  const endSession = useHardwareTestsStore((s) => s.endSession)
  const closeOpen = useHardwareTestsStore((s) => s.closeOpen)
  const hand = session.hand
  const steps = allSteps(session)

  return (
    <Panel
      title={session.plan_title}
      toolbar={
        <button className="btn btn-secondary" disabled={busy} onClick={() => void endSession()}>
          End session
        </button>
      }
    >
      <div className="hwt-meta">
        <span>session {session.id}</span>
        <span>started {formatTime(session.started_at)}</span>
        {session.finished_at && <span>finished {formatTime(session.finished_at)}</span>}
        <StepCounts steps={steps} />
      </div>
      <div className="hwt-facts">
        <span className="capability-badge on">{hand.label}</span>
        <span className="capability-badge">{hand.model_name ?? 'model unknown'}</span>
        <span className="capability-badge">{hand.side ?? 'side unknown'}</span>
        <span className="capability-badge">{hand.motor_family ?? 'motor family unknown'}</span>
        <span
          className="capability-badge"
          title={hand.hardware_version_source ? `from ${hand.hardware_version_source}` : undefined}
        >
          hw {formatHardwareVersion(hand.hardware_version)}
          {hand.hardware_version_source ? ` (${hand.hardware_version_source})` : ''}
        </span>
        {hand.capabilities.map((cap) => (
          <span key={cap} className="capability-badge on">
            {cap}
          </span>
        ))}
        {hand.mock && <span className="capability-badge warn">MOCK</span>}
        {(['main', 'branch'] as const).map((name) => {
          const side = session.sides[name]
          return (
            <span
              key={name}
              className={`capability-badge ${side?.available ? 'on' : 'warn'}`}
              title={side?.reason ?? side?.version ?? undefined}
            >
              {name}: {side?.available ? (side.version ?? 'available') : 'unavailable'}
            </span>
          )
        })}
      </div>
      {session.open_step && (
        <div className="hwt-recording on">
          <span className="hwt-rec-dot" /> step {session.open_step} is open and recording live
          readings
          <button className="btn btn-secondary" onClick={() => void closeOpen()}>
            Stop recording
          </button>
        </div>
      )}
      <div className="hwt-paths">
        <CopyPath label="summary" path={session.index_file} />
        <CopyPath label="results" path={session.results_dir} />
        {session.events_file && <CopyPath label="events" path={session.events_file} />}
        <details>
          <summary>Feature folders ({session.features.length})</summary>
          {session.features.map((feature) => (
            <CopyPath key={feature.id} label={feature.id} path={feature.folder} />
          ))}
        </details>
      </div>
    </Panel>
  )
}

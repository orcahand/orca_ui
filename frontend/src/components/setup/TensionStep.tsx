// Step 1: the slack test (each joint held, at most half a turn of slack, with
// the clicks that slack needs), then the tensioning. v2.1 hands get guided
// tensioning (move each finger against the holding motors, then ratchet the
// listed spools) and simple tensioning below it; v2.0 and unknown hands get
// simple tensioning only (the motors hold, you ratchet). Both aim a little
// loose: the tension sweep after calibration counts the clicks still missing.
// Currents and pull are adjusted inside the dialogs, which live in TensionDialogs.

import { useEffect, useState } from 'react'
import type { SlackJoint, TensionProgress } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import type { SetupVariant } from '../../state/setupVariant'
import { formatHardwareVersion, isV21Family, SLACK_CURRENT_CHOICES, useTensionFlow } from '../../state/tensionFlow'
import { FlowRowTitle, FlowStep, type StepState } from './FlowStep'
import { jointGroup, loadPassFractions } from './guidedSettings'
import { failToBanner, shortDate } from './setupUtils'
import { SLACK_HINT, startGuidedTension, startSlackTest } from './probeStart'

const GUIDED_INFO =
  'Finger by finger: the motors hold the pose at low current and you drive each joint by hand to both ends against their resistance, while the console scores how far each spool followed. Then ratchet the listed spools by the clicks shown, aiming a little loose; the tension sweep after calibration counts the rest.'
const SIMPLE_INFO =
  'The v2.0 protocol: activate the current so the motors hold every tendon, then ratchet each top spool clockwise until it clicks, aiming a little loose. Nothing is scored.'

export function TensionStep({ state, variant }: { state: StepState; variant: SetupVariant }) {
  const kai = variant === 'kai'
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const version = useAppStore((s) => s.status?.hardware_version ?? null)
  const operation = useOperationStore((s) => s.operation)
  const running =
    (operation?.kind === 'tension' || operation?.kind === 'guided_tension') &&
    isOperationActive(operation)

  const isV21 = isV21Family(version)
  const openHold = useTensionFlow((s) => s.openHold)
  const dismiss = useTensionFlow((s) => s.dismiss)
  // Restart wipes the saved scores, so it takes a second click to confirm.
  const [confirmRestart, setConfirmRestart] = useState(false)
  const slackCurrentMa = useTensionFlow((s) => s.slackCurrentMa)
  const setSlackCurrentMa = useTensionFlow((s) => s.setSlackCurrentMa)
  const slackTest = handInfo?.slack_test ?? null
  const slackBlock = slackTest?.block ?? null
  const slackMax = slackTest ? Math.max(0, ...Object.values(slackTest.results).map((r) => r.total_deg ?? 0)) : 0
  const slackClicks = slackTest ? clicksText(slackTest.results) : ''
  const runningKind = operation && isOperationActive(operation) ? operation.kind : null
  const slackState = slackBlock ? 'warn' : slackTest ? 'done' : 'next'
  const tensionState = slackBlock ? 'todo' : 'next'
  useEffect(() => {
    if (!confirmRestart) return
    const timer = window.setTimeout(() => setConfirmRestart(false), 4000)
    return () => window.clearTimeout(timer)
  }, [confirmRestart])

  // Guided tensioning is scored against the v2.1 travel baseline: v2.1 hands only.
  const guided = isV21 && handInfo?.guided_tension !== false
  const progress = guided
    ? ((kai ? handInfo?.tension_progress_slack : handInfo?.tension_progress) ?? null)
    : null
  const last = handInfo?.last_tension ?? null
  const blocked = gate.blocked
  const blockedReason = gate.reason ?? undefined
  // The hand family's currents; the guided dialog adjusts them during the run.
  const startGuided = (resume: boolean) => void startGuidedTension({ resume }).catch(failToBanner)

  const chip = progress ? (
    <ProgressChip progress={progress} kai={kai} />
  ) : last ? (
    <span
      title={`Last tensioned ${new Date(last.completed_at).toLocaleString()} (${
        last.mode === 'hold' ? 'hold and ratchet' : `guided, ${last.rounds ?? '?'} round${last.rounds === 1 ? '' : 's'}`
      })`}
    >
      {shortDate(last.completed_at)}
    </span>
  ) : undefined

  return (
    <FlowStep
      n={1}
      title="Tension"
      state={running ? 'running' : state}
      chip={chip}
      info={
        guided
          ? 'Slack test first, then guided tensioning (range-check every finger, ratchet the listed spools) or simple tensioning (the motors hold, you ratchet every top spool until it clicks).'
          : `Slack test first, then simple tensioning: the motors hold, you ratchet every top spool until it clicks. A ${formatHardwareVersion(version)} hand has no guided tensioning.`
      }
    >
      {running ? (
        <button className="btn btn-primary" onClick={() => dismiss(null)}>
          Return to session
        </button>
      ) : (
        <div className="calib-steps">
          <div className={`calib-step ${slackState}`}>
            <span className="calib-step-num">{slackState === 'done' ? '✓' : slackState === 'warn' ? '!' : 'a'}</span>
            <span>
              <FlowRowTitle title="Slack test" info={SLACK_HINT} />
              {slackTest && (
                <div className="calib-step-note">
                  {slackBlock
                    ? `${slackBlock}${slackClicks ? ` · ${slackClicks}` : ''}`
                    : `passed ${shortDate(slackTest.recorded_at)} · most slack ${slackMax.toFixed(0)}°${slackClicks ? ` · ${slackClicks}` : ''}`}
                </div>
              )}
            </span>
            <span className="calib-step-actions">
              <label className="flow-field" title="The winding current: enough to turn the spool through its slack against the held joint">
                <span>at</span>
                <select value={slackCurrentMa} onChange={(e) => setSlackCurrentMa(Number(e.target.value))}>
                  {SLACK_CURRENT_CHOICES.map((v) => (
                    <option key={v} value={v}>
                      {v} mA
                    </option>
                  ))}
                </select>
              </label>
              <button
                className={`btn ${slackState === 'done' ? 'btn-secondary' : 'btn-primary'}`}
                disabled={gate.blocked}
                title={gate.reason ?? SLACK_HINT}
                onClick={() => void startSlackTest().catch(failToBanner)}
              >
                {runningKind === 'slack_test' ? 'Running…' : slackTest ? 'Slack test again' : 'Slack test'}
              </button>
            </span>
          </div>
          {guided && (
            <div className={`calib-step ${tensionState}`}>
              <span className="calib-step-num">b</span>
              <span>
                <FlowRowTitle title="Guided tensioning" info={GUIDED_INFO} />
                {slackBlock && <div className="calib-step-note">pass the slack test first</div>}
              </span>
              <span className="calib-step-actions">
                {progress && (
                  <button
                    className={`btn ${confirmRestart ? 'btn-danger' : 'btn-secondary'}`}
                    disabled={blocked || !!slackBlock}
                    title="Forget the saved scores and check every joint again"
                    onClick={() => {
                      if (!confirmRestart) return setConfirmRestart(true)
                      setConfirmRestart(false)
                      startGuided(false)
                    }}
                  >
                    {confirmRestart ? 'Erase saved scores?' : 'Restart'}
                  </button>
                )}
                <button
                  className="btn btn-primary"
                  disabled={blocked || !!slackBlock}
                  title={blockedReason ?? slackBlock ?? undefined}
                  onClick={() => startGuided(true)}
                >
                  {progress ? 'Continue' : 'Start'}
                </button>
              </span>
            </div>
          )}
          <div className="calib-step next">
            <span className="calib-step-num">{guided ? 'c' : 'b'}</span>
            <span>
              <FlowRowTitle title="Simple tensioning" info={SIMPLE_INFO} />
            </span>
            <span className="calib-step-actions">
              <button
                className={`btn ${guided ? 'btn-secondary' : 'btn-primary'}`}
                disabled={gate.blocked}
                title={gate.reason ?? undefined}
                onClick={() => openHold(operation?.run_id ?? null)}
              >
                Start
              </button>
            </span>
          </div>
        </div>
      )}
    </FlowStep>
  )
}

// The joints whose slack still needs clicks: "index mcp ~3 clicks, …".
function clicksText(results: Record<string, SlackJoint>): string {
  return Object.entries(results)
    .filter(([, r]) => (r.clicks ?? 0) > 0)
    .sort(([, a], [, b]) => (b.clicks ?? 0) - (a.clicks ?? 0))
    .map(([joint, r]) => `${joint.replace('_', ' ')} ~${r.clicks} click${r.clicks === 1 ? '' : 's'}`)
    .join(', ')
}

function ProgressChip({ progress, kai }: { progress: TensionProgress; kai: boolean }) {
  if (kai) {
    const joints = Object.values(progress.scores ?? {})
    const passed = joints.filter((s) => s.status === 'pass').length
    return (
      <span title={`last round: ${passed} of ${joints.length} joints within tolerance · ${progress.rounds} round${progress.rounds === 1 ? '' : 's'} so far`}>
        {passed}/{joints.length}
      </span>
    )
  }
  const passes = loadPassFractions()
  const joints = Object.entries(progress.best ?? {})
  const passed = joints.filter(([joint, f]) => f >= passes[jointGroup(joint)]).length
  return (
    <span title={`${progress.rounds} round${progress.rounds === 1 ? '' : 's'}`}>
      {passed}/{joints.length}
    </span>
  )
}

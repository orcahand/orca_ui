// Step 2, in two parts: the calibration itself, automatic or by hand (the
// whole hand, or a subset picked in the settings drawer), and the tension sweep
// that compares the hand with the reference and counts the ratchet clicks
// still missing; the sweep window holds the motors for those clicks, then the
// hand is calibrated and swept once more. The slack test the calibration needs
// lives in the Tension step; a failed one still blocks calibrating here.
// Per-joint readiness shows as a row of dots, the joint name on hover.

import { useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { FlowProgress, FlowRowTitle, FlowRunning, FlowStep, type StepState } from './FlowStep'
import { failToBanner } from './setupUtils'
import { BaselinePicker, CalibrationRecords, SnapshotPromoter, TravelCheck, SlackEstimate } from './TravelBaselines'
import { SWEEP_HINT, startTensionSweep } from './probeStart'
import type { SetupVariant } from '../../state/setupVariant'
import { useTensionFlow } from '../../state/tensionFlow'
import { shortDate } from './setupUtils'

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']
function groupOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return GROUP_ORDER.includes(prefix) ? prefix : 'other'
}

// `bad` is the only state that means "calibrate this".
function jointMark(joint: JointInfo): 'ok' | 'bad' | 'na' {
  if (!joint.encoder_backed) return 'na'
  if (joint.encoder_calibrated === false || joint.loop_controlled === false) return 'bad'
  return joint.encoder_calibrated === true ? 'ok' : 'na'
}

export function CalibrateStep({ state, variant }: { state: StepState; variant: SetupVariant }) {
  // The kai page adds the travel snapshots and the slack estimate.
  const kai = variant === 'kai'
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation && isOperationActive(operation) && ['calibrate', 'slack_test', 'tension_sweep'].includes(operation.kind)
      ? operation
      : null

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [redoWrist, setRedoWrist] = useState(false)
  const joints = useMemo(() => handInfo?.joints ?? [], [handInfo])
  const absent = useMemo(() => new Set(handInfo?.absent_joints ?? []), [handInfo])
  const groups = useMemo(() => {
    const map = new Map<string, JointInfo[]>()
    for (const joint of joints) {
      const group = groupOf(joint.id)
      if (!map.has(group)) map.set(group, [])
      map.get(group)!.push(joint)
    }
    return [...map.entries()].sort(
      (a, b) => GROUP_ORDER.indexOf(a[0]) - GROUP_ORDER.indexOf(b[0]),
    )
  }, [joints])
  const missing = handInfo?.calibration.missing_anchors ?? []
  const needing = joints.filter((j) => jointMark(j) === 'bad').length
  const wristSelected = selected.has('wrist')
  const calibrated = handInfo?.calibration.motors === true
  // The newest slack test on this hand: a spool that turned half a turn blocks calibration.
  const slackTest = handInfo?.slack_test ?? null
  const slackBlock = slackTest?.block ?? null
  const sweep = handInfo?.tension_sweep ?? null
  const calibState = slackBlock ? 'warn' : calibrated ? 'done' : 'next'
  const sweepState = sweep?.latest ? 'done' : calibrated ? 'next' : 'todo'
  // Tendons the newest sweep says need clicks.
  const loose = Object.entries(sweep?.verdict ?? {}).filter(([, v]) => (v.clicks ?? 0) > 0)

  const toggle = (ids: string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      for (const id of ids) {
        if (on) next.add(id)
        else next.delete(id)
      }
      return next
    })

  const start = (manual = false) =>
    void api
      .operationStart('calibrate', {
        joints: selected.size > 0 ? [...selected] : null,
        force_wrist: redoWrist || wristSelected,
        ...(manual ? { manual: true } : {}),
      })
      .catch(failToBanner)
  const manualActive = active?.kind === 'calibrate' && active.params?.manual === true

  const settings = (
    <>
      <div className="flow-joint-grid">
        {groups.map(([group, groupJoints]) => {
          const ids = groupJoints.map((j) => j.id)
          const all = ids.filter((id) => !absent.has(id)).every((id) => selected.has(id))
          return (
            <div key={group} className="flow-joint-group">
              <button
                className={`finger-chip${all ? ' has-selection' : ''}`}
                onClick={() => toggle(ids.filter((id) => !absent.has(id)), !all)}
              >
                {group}
              </button>
              {groupJoints.map((joint) => (
                <label
                  key={joint.id}
                  className="joint-check"
                  title={absent.has(joint.id) ? `${joint.id}: no motor answered` : joint.id}
                  style={absent.has(joint.id) ? { opacity: 0.4 } : undefined}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(joint.id)}
                    disabled={absent.has(joint.id)}
                    onChange={(e) => toggle([joint.id], e.target.checked)}
                  />
                  {joint.id.split('_').slice(1).join('_') || joint.id}
                </label>
              ))}
            </div>
          )
        })}
      </div>
      <div className="flow-row">
        {missing.length > 0 && (
          <button className="setup-clear" onClick={() => setSelected(new Set(missing))}>
            pick {missing.length} missing
          </button>
        )}
        {selected.size > 0 && (
          <button className="setup-clear" onClick={() => setSelected(new Set())}>
            clear
          </button>
        )}
        {joints.some((j) => j.id === 'wrist') && (
          <label className="joint-check" title="The wrist is skipped once calibrated">
            <input
              type="checkbox"
              checked={redoWrist || wristSelected}
              disabled={wristSelected}
              onChange={(e) => setRedoWrist(e.target.checked)}
            />
            redo wrist
          </label>
        )}
      </div>
      <CalibrationRecords />
      {kai && (
        <>
          <BaselinePicker />
          <SnapshotPromoter />
          <TravelCheck />
          <SlackEstimate />
        </>
      )}
    </>
  )

  return (
    <FlowStep
      n={2}
      title="Calibrate"
      state={active ? 'running' : state}
      chip={needing > 0 ? `${needing} open` : joints.length ? 'all' : undefined}
      info="Drives each finger to its hardstops at the motor's own current ceiling, and the wrist at the console's current limit, then records the range. Keep clear while it runs."
      settings={settings}
    >
      {active ? (
        <>
          <FlowRunning phase={active.phase} detail={active.detail} />
          <FlowProgress value={active.progress} />
          {manualActive && (
            <button className="btn btn-secondary" onClick={() => useTensionFlow.getState().dismiss(null)}>
              Show manual calibration
            </button>
          )}
        </>
      ) : (
        <div className="calib-steps">
          <div className={`calib-step ${calibState}`}>
            <span className="calib-step-num">{calibState === 'done' ? '✓' : calibState === 'warn' ? '!' : 'a'}</span>
            <span>
              <div className="calib-step-title">Calibrate</div>
              <div className="calib-step-note">
                {slackBlock ? `${slackBlock} (Tension step)` : needing > 0 ? `${needing} joints open` : calibrated ? 'calibrated' : 'automatic: the motors drive every joint to its stops · manual: you hold each joint on its stops'}
              </div>
            </span>
            <span className="calib-step-actions">
              <button
                className={`btn ${calibState === 'next' ? 'btn-primary' : 'btn-secondary'}`}
                disabled={gate.blocked || !!slackBlock}
                title={gate.reason ?? slackBlock ?? 'The motors drive every joint to its hard stops. Keep clear.'}
                onClick={() => start()}
              >
                {selected.size > 0 ? `Automatic ${selected.size}` : 'Automatic'}
              </button>
              <button
                className="btn btn-secondary"
                disabled={gate.blocked || !!slackBlock}
                title={gate.reason ?? slackBlock ?? 'Torque off: hold each joint on its end stops by hand and press Enter to record'}
                onClick={() => start(true)}
              >
                {selected.size > 0 ? `Manual ${selected.size}` : 'Manual'}
              </button>
            </span>
          </div>
          <div className={`calib-step ${sweepState}`}>
            <span className="calib-step-num">{sweepState === 'done' ? '✓' : 'b'}</span>
            <span>
              <FlowRowTitle title="Tension sweep" info={SWEEP_HINT} />
              {(sweep?.latest || !calibrated) && (
                <div className="calib-step-note">
                  {sweep?.latest
                    ? `${sweep.latest}${sweep.latest_at ? ` · ${shortDate(sweep.latest_at)}` : ''}${sweep.reference ? ` · vs ${sweep.reference}` : ' · no reference for this motor family'}${loose.length ? ` · ${loose.map(([j, v]) => `${j.replace('_', ' ')} ~${v.clicks}`).join(', ')}` : ''}`
                    : 'needs a calibrated hand'}
                </div>
              )}
            </span>
            <span className="calib-step-actions">
              <button
                className={`btn ${sweepState === 'next' ? 'btn-primary' : 'btn-secondary'}`}
                disabled={gate.blocked || !calibrated}
                title={gate.reason ?? (calibrated ? SWEEP_HINT : 'calibrate first: the sweep runs between the calibrated limits')}
                onClick={() => void startTensionSweep().catch(failToBanner)}
              >
                Tension sweep
              </button>
            </span>
          </div>
        </div>
      )}
      {joints.length > 0 && (
        <div className="flow-dots">
          {joints.map((joint) => (
            <span key={joint.id} className={`flow-dot ${jointMark(joint)}`} title={joint.id} />
          ))}
        </div>
      )}
    </FlowStep>
  )
}

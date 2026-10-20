// Step 2: calibrate the whole hand, or a subset picked in the settings drawer.
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
import { FlowProgress, FlowRunning, FlowStep, type StepState } from './FlowStep'
import { failToBanner } from './setupUtils'

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

export function CalibrateStep({ state }: { state: StepState }) {
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation?.kind === 'calibrate' && isOperationActive(operation) ? operation : null

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

  const toggle = (ids: string[], on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev)
      for (const id of ids) {
        if (on) next.add(id)
        else next.delete(id)
      }
      return next
    })

  const start = () =>
    void api
      .operationStart('calibrate', {
        joints: selected.size > 0 ? [...selected] : null,
        force_wrist: redoWrist || wristSelected,
      })
      .catch(failToBanner)

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
    </>
  )

  return (
    <FlowStep
      n={2}
      title="Calibrate"
      state={active ? 'running' : state}
      chip={needing > 0 ? `${needing} open` : joints.length ? 'all' : undefined}
      info="Drives every joint to its hardstops at the console's current ceiling and records the range. Keep clear while it runs."
      settings={settings}
    >
      {active ? (
        <>
          <FlowRunning phase={active.phase} detail={active.detail} />
          <FlowProgress value={active.progress} />
        </>
      ) : (
        <button
          className="btn btn-primary"
          disabled={gate.blocked}
          title={gate.reason ?? undefined}
          onClick={start}
        >
          {selected.size > 0 ? `Calibrate ${selected.size}` : 'Calibrate'}
        </button>
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

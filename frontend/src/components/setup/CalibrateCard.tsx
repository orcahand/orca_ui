// Calibrate card: full-hand calibration or a per-joint subset. The API takes
// joint ids only — the finger chips here are pure frontend convenience that
// expand (same prefix grouping as EncoderPanel) to per-joint checkboxes.
// Also shows the per-joint encoder/calibration status from hand info.

import { useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']

function groupOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return GROUP_ORDER.includes(prefix) ? prefix : 'other'
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

function statusMark(joint: JointInfo): { text: string; cls: string } {
  if (!joint.encoder_backed) return { text: 'no enc', cls: 'na' }
  if (joint.encoder_calibrated === false) {
    return { text: 'enc ✓ · no anchor', cls: 'bad' }
  }
  // Anchor present but the feedback loop skipped the joint at connect:
  // its motor calibration is incomplete — it runs open-loop.
  if (joint.loop_controlled === false) {
    return { text: 'cal ✗ · open loop', cls: 'bad' }
  }
  if (joint.encoder_calibrated === true) {
    return { text: 'cal ✓ · enc ✓', cls: 'ok' }
  }
  return { text: 'enc ✓ · cal ?', cls: 'na' }
}

export function CalibrateCard() {
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation !== null &&
    operation.kind === 'calibrate' &&
    isOperationActive(operation)
      ? operation
      : null

  const [selectorOpen, setSelectorOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [forceWrist, setForceWrist] = useState(false)

  const joints = useMemo(() => handInfo?.joints ?? [], [handInfo])
  const calibration = handInfo?.calibration
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

  const toggleGroup = (group: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev)
      if (next.has(group)) next.delete(group)
      else next.add(group)
      return next
    })

  const toggleJoint = (jointId: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(jointId)) next.delete(jointId)
      else next.add(jointId)
      return next
    })

  const start = () =>
    void api
      .operationStart('calibrate', {
        joints: selected.size > 0 ? [...selected] : null,
        force_wrist: forceWrist,
      })
      .catch(fail)

  return (
    <div className="setup-card">
      <div className="setup-card-title">Calibrate</div>
      <p className="setup-card-hint">
        Drives each joint to its hardstops to find the motor range (and the
        encoder anchors, when encoders are present). Partial runs are safe —
        completed steps persist.
      </p>
      {active ? (
        <>
          <div className="setup-card-detail">
            {active.phase}
            {active.detail ? ` — ${active.detail}` : ''}
          </div>
          {active.progress !== null && (
            <div className="setup-progress">
              <div
                className="setup-progress-fill"
                style={{
                  width: `${Math.min(Math.max(active.progress, 0), 1) * 100}%`,
                }}
              />
            </div>
          )}
        </>
      ) : (
        <>
          {calibration?.hint && (
            <div className="setup-card-reason" style={{ color: 'var(--warn)' }}>
              {calibration.hint}{' '}
              <button
                className="setup-clear"
                onClick={() => {
                  setSelected(new Set(calibration.missing_anchors))
                  setSelectorOpen(true)
                }}
              >
                select those joints
              </button>
            </div>
          )}
          <div className="setup-card-row">
            <button
              className="btn btn-primary"
              disabled={gate.blocked}
              title={gate.reason ?? undefined}
              onClick={start}
            >
              {selected.size > 0
                ? `Calibrate selection (${selected.size})`
                : 'Calibrate all'}
            </button>
            <label className="joint-check" title="re-run the wrist even when it is already calibrated">
              <input
                type="checkbox"
                checked={forceWrist}
                onChange={(e) => setForceWrist(e.target.checked)}
              />
              force wrist
            </label>
          </div>
          {gate.blocked && (
            <div className="setup-card-reason">{gate.reason}</div>
          )}
          <button
            className="setup-expander"
            onClick={() => setSelectorOpen((open) => !open)}
          >
            {selectorOpen ? '▾' : '▸'} select joints
            {selected.size > 0 && (
              <span className="setup-expander-count">
                {' '}
                · {selected.size} selected
                <span
                  className="setup-clear"
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelected(new Set())
                  }}
                >
                  clear
                </span>
              </span>
            )}
          </button>
          {selectorOpen && (
            <div>
              <div className="finger-chip-row">
                {groups.map(([group, groupJoints]) => {
                  const count = groupJoints.filter((j) =>
                    selected.has(j.id),
                  ).length
                  return (
                    <button
                      key={group}
                      className={`finger-chip${
                        openGroups.has(group) ? ' open' : ''
                      }${count > 0 ? ' has-selection' : ''}`}
                      onClick={() => toggleGroup(group)}
                    >
                      {group}
                      {count > 0 ? ` ${count}/${groupJoints.length}` : ''}
                    </button>
                  )
                })}
              </div>
              {groups
                .filter(([group]) => openGroups.has(group))
                .map(([group, groupJoints]) => (
                  <div key={group} className="joint-check-list">
                    {groupJoints.map((joint) => (
                      <label key={joint.id} className="joint-check">
                        <input
                          type="checkbox"
                          checked={selected.has(joint.id)}
                          onChange={() => toggleJoint(joint.id)}
                        />
                        {joint.id}
                      </label>
                    ))}
                  </div>
                ))}
            </div>
          )}
        </>
      )}
      <div className="joint-status-list">
        {joints.map((joint) => {
          const mark = statusMark(joint)
          return (
            <div key={joint.id} className="joint-status-row">
              <span>{joint.id}</span>
              <span className={`joint-status-mark ${mark.cls}`}>
                {mark.text}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

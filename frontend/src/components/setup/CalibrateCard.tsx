// Calibrate on its own: the whole hand, or a per-joint subset. The API takes
// joint ids only — the finger chips here are pure frontend convenience that
// expand (same prefix grouping as EncoderPanel) to per-joint checkboxes.
// Also summarizes the per-joint calibration status from hand info.

import { useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { HoverNote } from '../common/HoverNote'

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']

function groupOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return GROUP_ORDER.includes(prefix) ? prefix : 'other'
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

// Plain-language readiness per joint; the technical state stays in the
// tooltip. `bad` is the only one that means "calibrate this".
function statusMark(joint: JointInfo): {
  text: string
  cls: string
  title: string
} {
  if (!joint.encoder_backed) {
    return {
      text: 'motor only',
      cls: 'na',
      title: 'no joint encoder here — calibration records its motor limits',
    }
  }
  if (joint.encoder_calibrated === false) {
    return {
      text: 'not calibrated',
      cls: 'bad',
      title: 'no encoder reference recorded — calibrate this joint',
    }
  }
  // Anchor present but the feedback loop skipped the joint at connect:
  // its motor calibration is incomplete — it runs open-loop.
  if (joint.loop_controlled === false) {
    return {
      text: 'not calibrated',
      cls: 'bad',
      title:
        'calibration is incomplete, so the hand cannot read this joint — ' +
        'it runs open-loop until you calibrate it again',
    }
  }
  if (joint.encoder_calibrated === true) {
    return {
      text: 'ready',
      cls: 'ok',
      title: 'motor limits and encoder reference recorded',
    }
  }
  return { text: 'unknown', cls: 'na', title: 'no calibration state reported' }
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
  // Tensioning invalidates the recorded ranges, so a finished tension run is
  // a standing instruction to calibrate until some other operation replaces it.
  const afterTension =
    operation !== null &&
    operation.kind === 'tension' &&
    operation.state === 'done'

  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [statusOpen, setStatusOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [redoWrist, setRedoWrist] = useState(false)

  const joints = useMemo(() => handInfo?.joints ?? [], [handInfo])
  const missingAnchors = handInfo?.calibration.missing_anchors ?? []
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

  const needing = joints.filter((j) => statusMark(j).cls === 'bad')
  const hasWrist = joints.some((j) => j.id === 'wrist')
  // Picking the wrist by hand is the explicit ask to re-run it — without the
  // force flag an already-calibrated wrist is skipped and the run does nothing.
  const wristSelected = selected.has('wrist')

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
        force_wrist: redoWrist || wristSelected,
      })
      .catch(fail)

  return (
    <div className="setup-card">
      <div className="setup-card-title">Calibrate</div>
      <p className="setup-copy">
        The hand drives every joint to its hardstops on its own and records the
        range it can reach. Keep clear while it runs.
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
          <HoverNote label="When to run it">
            After tensioning, after a lot of use, or when poses come out short.
            Stopping part-way keeps the joints it has already finished.
          </HoverNote>
          {afterTension && (
            <div className="setup-note accent">
              You have just tensioned the hand — calibrate now so the recorded
              ranges match the new tendon lengths.
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
                ? `Calibrate ${selected.size} selected`
                : 'Calibrate every joint'}
            </button>
            {selected.size > 0 && (
              <button
                className="btn btn-secondary"
                onClick={() => setSelected(new Set())}
              >
                clear selection
              </button>
            )}
          </div>
          {gate.blocked && (
            <div className="setup-card-reason">{gate.reason}</div>
          )}

          <div className="setup-advanced">
            <button
              className="setup-expander"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              {advancedOpen ? '▾' : '▸'} More options
              {selected.size > 0 && (
                <span className="setup-expander-count">
                  {' '}
                  · {selected.size} joints picked
                </span>
              )}
            </button>
            {advancedOpen && (
              <>
                <span className="setup-section-title">
                  Calibrate only some joints
                </span>
                <p className="setup-copy dim">
                  Everything else keeps the calibration it has.
                  {missingAnchors.length > 0 && (
                    <>
                      {' '}
                      <button
                        className="setup-clear"
                        onClick={() => {
                          setSelected(new Set(missingAnchors))
                          setOpenGroups(
                            new Set(missingAnchors.map((j) => groupOf(j))),
                          )
                        }}
                      >
                        pick the {missingAnchors.length} that need it
                      </button>
                    </>
                  )}
                </p>
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
                {hasWrist && (
                  <>
                    <span className="setup-section-title">The wrist</span>
                    <label className="joint-check">
                      <input
                        type="checkbox"
                        checked={redoWrist || wristSelected}
                        disabled={wristSelected}
                        onChange={(e) => setRedoWrist(e.target.checked)}
                      />
                      Redo the wrist as well
                    </label>
                    <p className="setup-option-hint">
                      The wrist keeps its calibration once set, so it is
                      normally skipped. Tick this if you took the wrist apart or
                      re-mounted it.
                      {wristSelected && ' Picking the wrist above turns it on.'}
                    </p>
                  </>
                )}
              </>
            )}
          </div>
        </>
      )}

      <div className="setup-advanced">
        <button
          className="setup-expander"
          onClick={() => setStatusOpen((open) => !open)}
        >
          {statusOpen ? '▾' : '▸'} Joint status
          <span
            className={`setup-summary ${needing.length > 0 ? 'warn' : 'ok'}`}
          >
            {' '}
            ·{' '}
            {needing.length > 0
              ? `${needing.length} of ${joints.length} need calibrating`
              : `all ${joints.length} calibrated`}
          </span>
        </button>
        {statusOpen && (
          <div className="joint-status-list">
            {joints.map((joint) => {
              const mark = statusMark(joint)
              return (
                <div key={joint.id} className="joint-status-row">
                  <span>{joint.id}</span>
                  <span
                    className={`joint-status-mark ${mark.cls}`}
                    title={mark.title}
                  >
                    {mark.text}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

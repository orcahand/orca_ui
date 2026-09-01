// Cable-integrity stress test: pick joints, then drive them hardstop to
// hardstop for N cycles. The joint picker mirrors CalibrateCard's (finger
// chips expanding to per-joint checkboxes) — the API takes joint ids only.
//
// While it runs the panel becomes the report: how far each joint actually
// settled at each extreme, and how much travel it is missing. That number is
// the whole point of the run — a stretching tendon stops reaching the end it
// was commanded to long before it fails outright.

import { useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type {
  JointInfo,
  OperationSnapshot,
  StressTestExtra,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { HoverNote } from '../common/HoverNote'
import { Panel } from '../common/Panel'

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']
const SPEEDS = [0.5, 1, 2, 4, 8]
// Mirrors stress.py: MAX_CYCLES / MAX_HOLD_S / MAX_MARGIN_DEG, and the
// player's MAX_INTERP_STEPS.
const MAX_CYCLES = 100_000_000
const MAX_HOLD_S = 5
const MAX_MARGIN_DEG = 15
const MAX_STEPS = 200
// Missing travel above this flags the joint as worth a look — roughly the
// player's arrival tolerance doubled, so ordinary tracking lag stays quiet.
const SHORTFALL_WARN_DEG = 3

function groupOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return GROUP_ORDER.includes(prefix) ? prefix : 'other'
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const clamp = (value: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, value))

function stressExtra(op: OperationSnapshot | null): StressTestExtra | null {
  if (!op || op.kind !== 'stress_test' || !op.extra) return null
  return op.extra as unknown as StressTestExtra
}

export function StressTestPanel() {
  const gate = useStartGate('motors')
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const operation = useOperationStore((s) => s.operation)

  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [cycles, setCycles] = useState(20)
  const [loop, setLoop] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [holdS, setHoldS] = useState(0.25)
  const [marginDeg, setMarginDeg] = useState(0)
  const [thumbOpposed, setThumbOpposed] = useState(true)
  // Park every unpicked joint fully outwards for the run, optionally leaving
  // the abduction joints out of that hold.
  const [holdRest, setHoldRest] = useState(false)
  const [freezeAbduction, setFreezeAbduction] = useState(false)
  // Interpolation steps per leg, as typed. '' = the cruise-speed glide;
  // 0 = one command straight to the extreme, at motor speed.
  const [steps, setSteps] = useState('')

  // A joint with no motor cannot be driven anywhere — the backend rejects
  // those, so they never make it into the picker.
  const drivable = useMemo(
    () => (joints ?? []).filter((j) => j.motor_id !== null),
    [joints],
  )
  const groups = useMemo(() => {
    const map = new Map<string, JointInfo[]>()
    for (const joint of drivable) {
      const group = groupOf(joint.id)
      if (!map.has(group)) map.set(group, [])
      map.get(group)!.push(joint)
    }
    return [...map.entries()].sort(
      (a, b) => GROUP_ORDER.indexOf(a[0]) - GROUP_ORDER.indexOf(b[0]),
    )
  }, [drivable])

  const active =
    operation !== null &&
    operation.kind === 'stress_test' &&
    isOperationActive(operation)
      ? operation
      : null
  // The last finished run's report stays on screen until another operation
  // replaces it — it is the result you came for, not a transient.
  const finished =
    operation !== null &&
    operation.kind === 'stress_test' &&
    operation.state === 'done'
      ? operation
      : null

  // '' = glide at cruise speed; a number = that many waypoints per leg,
  // 0 meaning a single command to the extreme.
  const stepsTyped = steps.trim() !== ''
  const parsedSteps = stepsTyped ? parseInt(steps, 10) : null
  const stepsOk = parsedSteps === null || Number.isFinite(parsedSteps)
  const blocked =
    gate.blocked || !torqueOn || selected.size === 0 || !stepsOk
  const reason = gate.blocked
    ? gate.reason
    : !torqueOn
      ? 'enable torque to run a stress test'
      : selected.size === 0
        ? 'pick at least one joint'
        : !stepsOk
          ? 'steps must be a whole number (or blank to glide)'
          : null

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

  // Chip click opens the group; the chip's own tick box takes/releases every
  // joint in it, which is how you pick a whole finger in one action.
  const toggleWholeGroup = (groupJoints: JointInfo[]) =>
    setSelected((prev) => {
      const next = new Set(prev)
      const allOn = groupJoints.every((j) => next.has(j.id))
      for (const joint of groupJoints) {
        if (allOn) next.delete(joint.id)
        else next.add(joint.id)
      }
      return next
    })

  const start = () => {
    if (blocked) return
    void api
      .operationStart('stress_test', {
        joints: [...selected],
        speed,
        hold_s: holdS,
        margin_deg: marginDeg,
        thumb_opposed: thumbOpposed,
        hold_rest: holdRest,
        freeze_abduction: freezeAbduction,
        ...(loop ? { loop: true } : { cycles }),
        ...(parsedSteps !== null && Number.isFinite(parsedSteps)
          ? { interp_steps: clamp(parsedSteps, 0, MAX_STEPS) }
          : {}),
      })
      .catch(fail)
  }

  const extra = stressExtra(active) ?? stressExtra(finished)

  return (
    <Panel title="Stress Test">
      <p className="stress-copy">
        Drives the joints you pick from one end of their range to the other,
        over and over, holding at each end until the hand gets there. Use it
        to work a repaired tendon or to check cable integrity — the report
        below shows how much travel each joint is still managing. The thumb
        runs in counter-phase: it opens as the fingers close. Joints you did
        not pick are left alone, or held fully outwards for the whole run if
        you tick <em>hold rest open</em>.
      </p>
      <HoverNote label="Before you start">
        The hand moves to its hardstops at full travel and keeps going until
        the cycle count runs out or you stop it. Keep hands and cables clear,
        and give it room. Stop and E-stop both end it immediately; pause
        parks it mid-cycle.
      </HoverNote>

      {active ? (
        <RunningStrip
          detail={active.detail}
          progress={active.progress}
          paused={active.state === 'paused'}
        />
      ) : (
        <>
          <div className="finger-chip-row">
            {groups.map(([group, groupJoints]) => {
              const count = groupJoints.filter((j) => selected.has(j.id)).length
              return (
                <span key={group} className="stress-chip-pair">
                  <input
                    type="checkbox"
                    aria-label={`select every ${group} joint`}
                    title={`select every ${group} joint`}
                    checked={count === groupJoints.length}
                    ref={(el) => {
                      if (el) {
                        el.indeterminate =
                          count > 0 && count < groupJoints.length
                      }
                    }}
                    onChange={() => toggleWholeGroup(groupJoints)}
                  />
                  <button
                    className={`finger-chip${
                      openGroups.has(group) ? ' open' : ''
                    }${count > 0 ? ' has-selection' : ''}`}
                    onClick={() => toggleGroup(group)}
                  >
                    {group}
                    {count > 0 ? ` ${count}/${groupJoints.length}` : ''}
                  </button>
                </span>
              )
            })}
            <button
              className="finger-chip"
              onClick={() => setSelected(new Set(drivable.map((j) => j.id)))}
            >
              all
            </button>
            {selected.size > 0 && (
              <button
                className="finger-chip"
                onClick={() => setSelected(new Set())}
              >
                clear
              </button>
            )}
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
                    <span className="stress-rom">
                      {joint.rom[0]}…{joint.rom[1]}°
                    </span>
                  </label>
                ))}
              </div>
            ))}

          <div className="stress-form">
            <label className="stress-field">
              cycles
              <input
                type="number"
                min={1}
                max={MAX_CYCLES}
                disabled={loop}
                value={cycles}
                onChange={(e) =>
                  setCycles(
                    clamp(Math.round(Number(e.target.value) || 1), 1, MAX_CYCLES),
                  )
                }
              />
            </label>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={loop}
                onChange={(e) => setLoop(e.target.checked)}
              />
              nonstop
            </label>
            <label className="stress-field">
              speed
              <select
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              >
                {SPEEDS.map((value) => (
                  <option key={value} value={value}>
                    ×{value}
                  </option>
                ))}
              </select>
            </label>
            <label className="stress-field">
              hold
              <input
                type="number"
                min={0}
                max={MAX_HOLD_S}
                step={0.05}
                value={holdS}
                onChange={(e) =>
                  setHoldS(clamp(Number(e.target.value) || 0, 0, MAX_HOLD_S))
                }
              />
              s
            </label>
            <label className="stress-field">
              margin
              <input
                type="number"
                min={0}
                max={MAX_MARGIN_DEG}
                step={0.5}
                value={marginDeg}
                onChange={(e) =>
                  setMarginDeg(
                    clamp(Number(e.target.value) || 0, 0, MAX_MARGIN_DEG),
                  )
                }
              />
              °
            </label>
            <label className="stress-field">
              steps
              <input
                type="number"
                min={0}
                max={MAX_STEPS}
                placeholder="glide"
                title={
                  'waypoints between the two extremes — 0 sends one command ' +
                  'straight to the extreme and the motors run the whole ' +
                  'range at their own speed; blank keeps the smooth ' +
                  'cruise-speed glide'
                }
                value={steps}
                onChange={(e) => setSteps(e.target.value)}
              />
            </label>
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={thumbOpposed}
                onChange={(e) => setThumbOpposed(e.target.checked)}
              />
              thumb opposed
            </label>
            <label
              className="toggle-label"
              title={
                'park every joint you did not pick at its outward limit and ' +
                'hold it there — the rest of the hand stays splayed clear ' +
                'of the joints being cycled instead of drifting'
              }
            >
              <input
                type="checkbox"
                checked={holdRest}
                onChange={(e) => setHoldRest(e.target.checked)}
              />
              hold rest open
            </label>
            <label
              className="toggle-label"
              title={
                holdRest
                  ? 'leave the abduction joints out of that hold, so they ' +
                    'stay where they are instead of fanning out'
                  : 'only applies while the rest of the hand is held open'
              }
            >
              <input
                type="checkbox"
                disabled={!holdRest}
                checked={freezeAbduction}
                onChange={(e) => setFreezeAbduction(e.target.checked)}
              />
              freeze abduction
            </label>
            <button
              className="btn btn-danger"
              disabled={blocked}
              title={reason ?? 'start the stress test'}
              onClick={start}
            >
              ▲▼ stress test
            </button>
            <span className={`stress-note${reason ? ' warn' : ''}`}>
              {reason ??
                `${selected.size} joint${selected.size > 1 ? 's' : ''} · ` +
                  `${loop ? 'nonstop' : `${cycles} cycles`}` +
                  (marginDeg > 0 ? ` · ${marginDeg}° off each hardstop` : '') +
                  ` · ${
                    parsedSteps === null
                      ? 'gliding'
                      : parsedSteps <= 0
                        ? 'straight to each extreme at motor speed'
                        : `${parsedSteps} steps per leg`
                  }` +
                  (thumbOpposed ? ' · thumb opposed' : '') +
                  (holdRest
                    ? ` · rest held open${
                        freezeAbduction ? ', abduction frozen' : ''
                      }`
                    : '')}
            </span>
          </div>
        </>
      )}

      {extra && <ReachTable extra={extra} live={active !== null} />}
    </Panel>
  )
}

// The panel's own in-place progress. The transport bar carries the controls
// (pause / stop) for every tab; this just keeps the count next to the report.
function RunningStrip({
  detail,
  progress,
  paused,
}: {
  detail: string | null
  progress: number | null
  paused: boolean
}) {
  return (
    <div className="stress-running">
      <span className="stress-running-detail">
        {paused ? 'paused — ' : ''}
        {detail ?? 'running'}
      </span>
      {progress !== null && (
        <div className="setup-progress">
          <div
            className="setup-progress-fill"
            style={{ width: `${clamp(progress, 0, 1) * 100}%` }}
          />
        </div>
      )}
    </div>
  )
}

function ReachTable({
  extra,
  live,
}: {
  extra: StressTestExtra
  live: boolean
}) {
  if (!extra.measured) {
    return (
      <div className="panel-hint">
        no joint-angle source — the cycles run, but the travel each joint
        achieves cannot be measured
      </div>
    )
  }
  return (
    <table className="traj-table stress-table">
      <thead>
        <tr>
          <th>joint</th>
          <th>commanded</th>
          <th>reached</th>
          <th>travel</th>
          <th>missing</th>
        </tr>
      </thead>
      <tbody>
        {extra.joints.map((row) => {
          const missing = row.span_shortfall_deg
          const warn = missing !== null && missing > SHORTFALL_WARN_DEG
          return (
            <tr key={row.id}>
              <td className="traj-name">{row.id}</td>
              <td>
                {row.target[0].toFixed(0)}…{row.target[1].toFixed(0)}°
              </td>
              <td>
                {row.reached
                  ? `${row.reached[0].toFixed(1)}…${row.reached[1].toFixed(1)}°`
                  : live
                    ? '…'
                    : '—'}
              </td>
              <td>
                {row.span_deg !== null
                  ? `${row.span_deg.toFixed(1)} / ${row.commanded_span_deg.toFixed(0)}°`
                  : '—'}
              </td>
              <td
                className={warn ? 'stress-missing warn' : 'stress-missing'}
                title={
                  row.worst_shortfall_deg !== null
                    ? `worst single-end miss this run: ${row.worst_shortfall_deg.toFixed(1)}°`
                    : undefined
                }
              >
                {missing !== null ? `${missing.toFixed(1)}°` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

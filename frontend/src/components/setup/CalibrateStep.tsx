// Step 2, in three parts: the calibration itself, automatic or by hand (the
// whole hand, or a subset picked in the settings drawer), the tension sweep
// that compares the hand with the reference and counts the ratchet clicks
// still missing, and, when it lists any, tensioning those motors again before
// calibrating and sweeping once more. The slack test the calibration needs lives in the
// Tension step; a failed one still blocks calibrating here. Per-joint
// readiness shows as a row of dots, the joint name on hover.

import { useEffect, useMemo, useState } from 'react'
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
import { CalibrationRecords, SnapshotPromoter, TravelCheck, SlackEstimate } from './TravelBaselines'
import { SWEEP_HINT, startGuidedTension, startTensionSweep } from './probeStart'
import type { SetupVariant } from '../../state/setupVariant'
import { SWEEP_REPEAT_CHOICES, useTensionFlow } from '../../state/tensionFlow'
import { shortDate } from './setupUtils'

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']
const MIN_CURRENT_MA = 20
type CurrentGroup = 'abd' | 'mcp' | 'pip'
// Mirrors calibration_group() in orca_core's hand_config.py.
const CURRENT_GROUPS: { key: CurrentGroup; label: string; hint: string }[] = [
  { key: 'abd', label: 'abd', hint: 'abductions + thumb cmc' },
  { key: 'mcp', label: 'mcp', hint: 'all MCP joints' },
  { key: 'pip', label: 'pip', hint: 'PIPs + thumb dip' },
]
// Keyed "all" for the one-current form, or a group; null keeps the hand's value.
type CurrentOverrides = Partial<Record<'all' | CurrentGroup, number>>
const currentKey = (family: string) => `orca.calibrate.currents.${family}`

function loadCurrents(family: string): CurrentOverrides {
  try {
    const stored = JSON.parse(localStorage.getItem(currentKey(family)) ?? 'null')
    if (stored && typeof stored === 'object') return stored
  } catch {
    /* unreadable: no overrides */
  }
  return {}
}

function saveCurrents(family: string, overrides: CurrentOverrides): void {
  try {
    if (Object.keys(overrides).length) localStorage.setItem(currentKey(family), JSON.stringify(overrides))
    else localStorage.removeItem(currentKey(family))
  } catch {
    /* storage unavailable: the values last this page load */
  }
}

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
  // Calibration currents for this run; an unset field keeps the hand's own value.
  const family = handInfo?.guided_tension_defaults?.motor_type ?? 'dynamixel'
  const currentInfo = handInfo?.calibration_current ?? null
  const groupDefaults = currentInfo?.groups ?? null
  const [overrides, setOverrides] = useState<CurrentOverrides>({})
  useEffect(() => setOverrides(loadCurrents(family)), [family])
  const maxCurrent = currentInfo?.max ?? null
  const inRange = (v: number) => v >= MIN_CURRENT_MA && (maxCurrent === null || v <= maxCurrent)
  const fields = groupDefaults
    ? CURRENT_GROUPS.map((g) => ({ ...g, placeholder: groupDefaults[g.key] }))
    : [{ key: 'all' as const, label: 'current', hint: 'every joint', placeholder: currentInfo?.default }]
  const activeCurrents = fields.flatMap((f) => (overrides[f.key] !== undefined ? [[f.key, overrides[f.key]!] as const] : []))
  const currentValid = activeCurrents.every(([, v]) => inRange(v))
  const changeCurrent = (key: 'all' | CurrentGroup, value: number | null) => {
    const next = { ...overrides }
    if (value === null) delete next[key]
    else next[key] = value
    setOverrides(next)
    saveCurrents(family, next)
  }
  const currentParams = groupDefaults
    ? { calibration_currents: activeCurrents.length ? Object.fromEntries(activeCurrents) : null }
    : { calibration_current: overrides.all ?? null }
  const currentChip = activeCurrents.length
    ? activeCurrents.map(([k, v]) => (k === 'all' ? `${v} mA` : `${k} ${v}`)).join(' · ')
    : null
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
  const sweepRepeats = useTensionFlow((s) => s.sweepRepeats)
  const setSweepRepeats = useTensionFlow((s) => s.setSweepRepeats)
  const runNote = useTensionFlow((s) => s.runNote)
  const setRunNote = useTensionFlow((s) => s.setRunNote)
  const calibState = slackBlock ? 'warn' : calibrated ? 'done' : 'next'
  const sweepState = sweep?.latest ? 'done' : calibrated ? 'next' : 'todo'
  // Tendons the newest sweep says need clicks, with their friction as a share
  // of the reference's and the click count.
  const loose = Object.entries(sweep?.verdict ?? {})
    .filter(([, v]) => (v.clicks ?? 0) > 0)
    .map(([joint, v]) => [joint, { pct: v.share != null ? Math.round(v.share * 100) : null, clicks: v.clicks ?? null }] as const)
  const againState = loose.length ? 'next' : sweep?.latest ? 'done' : 'todo'
  const tensionAgain = () =>
    void startGuidedTension({ ratchet_joints: Object.fromEntries(loose), start_at: 'tension' }).catch(failToBanner)

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
        ...(manual ? { manual: true } : currentParams),
      })
      .catch(failToBanner)
  const manualActive = active?.kind === 'calibrate' && active.params?.manual === true

  const settings = (
    <>
      <div className="flow-fields">
        {fields.map((f) => {
          const value = overrides[f.key]
          return (
            <label
              key={f.key}
              className="flow-field"
              title={`Calibration current · ${f.hint}${maxCurrent ? ` (${MIN_CURRENT_MA}–${maxCurrent} mA)` : ''}`}
            >
              <span>{f.label}</span>
              <input
                type="number"
                min={MIN_CURRENT_MA}
                max={maxCurrent ?? undefined}
                step={10}
                placeholder={f.placeholder != null ? String(f.placeholder) : undefined}
                value={value ?? ''}
                className={value === undefined || inRange(value) ? undefined : 'invalid'}
                onChange={(e) => changeCurrent(f.key, e.target.value === '' ? null : Number(e.target.value))}
              />
              <span className="flow-unit">mA</span>
            </label>
          )
        })}
        {activeCurrents.length > 0 && (
          <button
            className="setup-clear"
            onClick={() => {
              setOverrides({})
              saveCurrents(family, {})
            }}
          >
            reset
          </button>
        )}
      </div>
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
      chip={
        currentChip
          ? `${needing > 0 ? `${needing} open · ` : ''}${currentChip}`
          : needing > 0 ? `${needing} open` : joints.length ? 'all' : undefined
      }
      info="Drives every joint to its hardstops and records the range. Keep clear while it runs."
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
                disabled={gate.blocked || !currentValid || !!slackBlock}
                title={gate.reason ?? slackBlock ?? (!currentValid ? 'calibration current out of range' : undefined)}
                onClick={() => start()}
              >
                {selected.size > 0 ? `Calibrate ${selected.size}` : 'Calibrate'}
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
              <div className="calib-step-title">Tension sweep</div>
              <div className="calib-step-note">
                {sweep?.latest
                  ? `${sweep.latest}${sweep.latest_at ? ` · ${shortDate(sweep.latest_at)}` : ''}${sweep.reference ? ` · vs ${sweep.reference}` : ' · no reference for this motor family'}`
                  : calibrated
                    ? `friction along every joint's travel vs the reference curves${sweep?.reference ? ` (${sweep.reference})` : ''}; counts the clicks still missing`
                    : 'needs a calibrated hand'}
              </div>
            </span>
            <span className="calib-step-actions">
              <label className="flow-field" title="Saved with the measurement, e.g. 'before clicks' or 'after 1 click'">
                <span>note</span>
                <input type="text" value={runNote} placeholder="label this run" onChange={(e) => setRunNote(e.target.value)} />
              </label>
              <label className="flow-field" title="Passes limit to limit and back per joint; the currents are averaged">
                <span>passes</span>
                <select value={sweepRepeats} onChange={(e) => setSweepRepeats(Number(e.target.value))}>
                  {SWEEP_REPEAT_CHOICES.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
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
          <div className={`calib-step ${againState}`}>
            <span className="calib-step-num">{againState === 'done' ? '✓' : 'c'}</span>
            <span>
              <div className="calib-step-title">Tension again</div>
              <div className="calib-step-note">
                {loose.length
                  ? `${loose.map(([j, r]) => `${j.replace('_', ' ')}${r.clicks ? ` ~${r.clicks} click${r.clicks === 1 ? '' : 's'}` : r.pct != null ? ` ${r.pct} %` : ''}`).join(', ')} · ratchet, then calibrate and sweep again`
                  : sweep?.latest && sweep.reference
                    ? 'no clicks needed — go on to Run'
                    : 'only if the measurement flags a tendon'}
              </div>
            </span>
            <span className="calib-step-actions">
              <button
                className={`btn ${againState === 'next' ? 'btn-primary' : 'btn-secondary'}`}
                disabled={gate.blocked || !loose.length}
                title={gate.reason ?? (loose.length ? 'Open guided tensioning at the ratchet step with these tendons listed' : 'nothing flagged by the last measurement')}
                onClick={tensionAgain}
              >
                Tension {loose.length ? loose.length : ''} again
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

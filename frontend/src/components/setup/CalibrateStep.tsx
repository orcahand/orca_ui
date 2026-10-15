// Step 2: calibrate the whole hand, or a subset picked in the settings drawer.
// Per-joint readiness shows as a row of dots, the joint name on hover.

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
import { useTensionFlow } from '../../state/tensionFlow'

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

export function CalibrateStep({ state }: { state: StepState }) {
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation?.kind === 'calibrate' && isOperationActive(operation) ? operation : null

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
  const manualActive = active?.params?.manual === true

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
        <div className="flow-row">
          <button
            className="btn btn-primary"
            disabled={gate.blocked || !currentValid}
            title={gate.reason ?? (!currentValid ? 'calibration current out of range' : undefined)}
            onClick={() => start()}
          >
            {selected.size > 0 ? `Calibrate ${selected.size}` : 'Calibrate'}
          </button>
          <button
            className="btn btn-secondary"
            disabled={gate.blocked}
            title={gate.reason ?? 'Torque off: hold each joint on its end stops by hand and press Enter to record'}
            onClick={() => start(true)}
          >
            {selected.size > 0 ? `Manual calibration ${selected.size}` : 'Manual calibration'}
          </button>
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

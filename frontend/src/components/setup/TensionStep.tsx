// Step 1, in two parts: the slack test (each joint held, at most half a turn
// of slack, with the clicks that slack needs) and the tensioning itself, which
// aims a little loose: the tension sweep after calibration counts the clicks
// still missing. v2.1 hands get guided tensioning; v2.0 and unknown hands get
// the hold dialog. The dialogs live in TensionDialogs.

import { useEffect, useState } from 'react'
import type { SlackJoint, TensionProgress } from '../../api/types'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import type { SetupVariant } from '../../state/setupVariant'
import {
  formatHardwareVersion,
  DEFAULT_OFFSET_DEG,
  OFFSET_BOUNDS_DEG,
  useTensionFlow,
  useTensionMode,
  type TensionMode,
} from '../../state/tensionFlow'
import { FlowStep, type StepState } from './FlowStep'
import { jointGroup, loadPassFractions, loadPassSlack } from './guidedSettings'
import { failToBanner, shortDate } from './setupUtils'
import { BaselinePicker } from './TravelBaselines'
import { SLACK_HINT, startSlackTest } from './probeStart'
import { SLACK_CURRENT_CHOICES } from '../../state/tensionFlow'

const MODE_LABEL: Record<TensionMode, string> = {
  guided: 'guided',
  hold: 'hold & ratchet',
}

export function TensionStep({ state, variant }: { state: StepState; variant: SetupVariant }) {
  const kai = variant === 'kai'
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const version = useAppStore((s) => s.status?.hardware_version ?? null)
  const operation = useOperationStore((s) => s.operation)
  const running =
    (operation?.kind === 'tension' || operation?.kind === 'guided_tension') &&
    isOperationActive(operation)

  const { mode, natural, forced, isV21 } = useTensionMode()
  const setForced = useTensionFlow((s) => s.setForced)
  const openHold = useTensionFlow((s) => s.openHold)
  const dismiss = useTensionFlow((s) => s.dismiss)
  const offsetDeg = useTensionFlow((s) => s.offsetDeg)
  const setOffsetDeg = useTensionFlow((s) => s.setOffsetDeg)

  const familyDefaults = handInfo?.guided_tension_defaults
  const family = familyDefaults?.motor_type ?? 'dynamixel'
  const [overrides, setOverrides] = useState<Partial<GuidedCurrents>>({})
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
  useEffect(() => setOverrides(loadOverrides(family)), [family])
  const currents: GuidedCurrents = { ...pickCurrents(familyDefaults), ...overrides }
  // An emptied field goes back to the family default.
  const setCurrent = (key: keyof GuidedCurrents, value: number | null) => {
    const next = { ...overrides }
    if (value === null) delete next[key]
    else next[key] = value
    setOverrides(next)
    saveOverrides(family, next)
  }

  useEffect(() => {
    // Forcing guided on a hand that gets it anyway is a no-op; drop the stale choice.
    if (forced === 'guided' && natural === 'guided') setForced(null)
  }, [forced, natural, setForced])
  const guided = mode === 'guided' && handInfo?.guided_tension !== false
  const progress = guided
    ? ((kai ? handInfo?.tension_progress_slack : handInfo?.tension_progress) ?? null)
    : null
  const last = handInfo?.last_tension ?? null
  const offsetValid = offsetDeg >= OFFSET_BOUNDS_DEG[0] && offsetDeg <= OFFSET_BOUNDS_DEG[1]
  const settingsValid =
    offsetValid && (!guided || CURRENT_FIELDS.every((f) => inBounds(currents[f.key], f)))
  const blocked = gate.blocked || !settingsValid
  const blockedReason = gate.reason ?? (settingsValid ? undefined : 'a tension setting is out of range')

  const startGuided = (resume: boolean) =>
    void api
      .operationStart('guided_tension', {
        ...currents,
        tension_offset_deg: offsetDeg,
        ...(kai
          ? { scoring: 'slack', pass_slack_deg: loadPassSlack() }
          : { scoring: 'fraction', pass_fractions: loadPassFractions() }),
        resume,
        any_hardware: !isV21,
      })
      .catch(failToBanner)

  const chip = progress ? (
    <ProgressChip progress={progress} kai={kai} />
  ) : last ? (
    shortDate(last.completed_at)
  ) : undefined

  const settings = (
    <>
      <div className="flow-row">
        <label className="flow-field" title="Which tensioning dialog opens">
          <span>dialog</span>
          <select
            value={forced ?? ''}
            onChange={(e) => setForced((e.target.value || null) as TensionMode | null)}
          >
            <option value="">
              auto · {MODE_LABEL[natural]} ({formatHardwareVersion(version)})
            </option>
            {natural === 'hold' && (
              <option value="guided">force guided (score a non-v2.1 hand against the v2.1 baseline)</option>
            )}
            <option value="hold">force hold &amp; ratchet</option>
          </select>
        </label>
      </div>
      {forced === 'guided' && !isV21 && (
        <div className="flow-info warn">
          scores this {formatHardwareVersion(version)} hand against the v2.1 baseline
        </div>
      )}
      {(handInfo?.absent_joints?.length ?? 0) > 0 && (
        <div className="flow-info warn" title={`motors ${(handInfo?.absent_motors ?? []).join(', ')}`}>
          no motor answered for {handInfo!.absent_joints!.join(', ')} — these joints are left out
        </div>
      )}
      <div className="flow-row">
        <label
          className="flow-field"
          title="How far the finger motors turn counterclockwise while you ratchet, loading the bottom spools"
        >
          <span>pull</span>
          <input
            type="number"
            min={OFFSET_BOUNDS_DEG[0]}
            max={OFFSET_BOUNDS_DEG[1]}
            step={5}
            value={offsetDeg}
            className={offsetValid ? undefined : 'invalid'}
            onChange={(e) => setOffsetDeg(e.target.value === '' ? DEFAULT_OFFSET_DEG : Number(e.target.value))}
          />
          <span className="flow-unit">°</span>
        </label>
      </div>
      {kai && guided && <BaselinePicker />}
      {guided ? (
        <details className="flow-advanced">
          <summary className="flow-field">Advanced settings</summary>
        <div className="flow-fields">
          {CURRENT_FIELDS.map((field) => (
            <label key={field.key} className="flow-field" title={field.hint}>
              <span>{field.label}</span>
              <input
                type="number"
                min={field.min}
                max={field.max}
                step={10}
                value={currents[field.key]}
                className={inBounds(currents[field.key], field) ? undefined : 'invalid'}
                onChange={(e) => setCurrent(field.key, e.target.value === '' ? null : Number(e.target.value))}
              />
              <span className="flow-unit">mA</span>
            </label>
          ))}
          <button
            className="setup-clear"
            onClick={() => {
              setOverrides({})
              saveOverrides(family, {})
            }}
          >
            reset
          </button>
        </div>
        </details>
      ) : null}
    </>
  )

  return (
    <FlowStep
      n={1}
      title="Tension"
      state={running ? 'running' : state}
      chip={chip}
      info={
        guided
          ? 'Guided: range-check every finger, then ratchet each top spool clockwise until it clicks. Green once every joint passes.'
          : 'Activate the current so the motors hold the tendons, then ratchet each top spool clockwise until it clicks.'
      }
      settings={settings}
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
              <div className="calib-step-title">Slack test</div>
              <div className="calib-step-note">
                {slackBlock
                  ? `${slackBlock}${slackClicks ? ` · ${slackClicks}` : ''}`
                  : slackTest
                    ? `passed ${shortDate(slackTest.recorded_at)} · most slack ${slackMax.toFixed(0)}°${slackClicks ? ` · ${slackClicks}` : ''}`
                    : 'hold each joint while its motor winds; at most half a turn of slack'}
              </div>
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
          <div className={`calib-step ${tensionState}`}>
            <span className="calib-step-num">b</span>
            <span>
              <div className="calib-step-title">Tension</div>
              <div className="calib-step-note">
                {slackBlock
                  ? 'pass the slack test first'
                  : guided
                    ? 'move each finger → ratchet the listed spools, aiming a little loose; the sweep after calibration counts the rest'
                    : 'activate the current and ratchet every top spool until it clicks, aiming a little loose'}
              </div>
            </span>
            <span className="calib-step-actions">
              {guided && progress && (
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
                onClick={() => (guided ? startGuided(true) : openHold(operation?.run_id ?? null))}
              >
                {guided && progress ? 'Continue' : 'Start'}
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

interface GuidedCurrents {
  hold_ap: number
  hold_mcp: number
  hold_pip: number
  tension_current: number
}

const overridesKey = (family: string) => `orca.guidedTension.currents.v3.${family}`
// Only used until the backend reports the hand's family defaults.
const DEFAULT_CURRENTS: GuidedCurrents = {
  hold_ap: 200,
  hold_mcp: 140,
  hold_pip: 100,
  tension_current: 400,
}
// Bounds mirror CURRENT_BOUNDS_MA in orca_ui/hand/operations/guided_tension.py.
const CURRENT_FIELDS: {
  key: keyof GuidedCurrents
  label: string
  hint: string
  min: number
  max: number
}[] = [
  { key: 'hold_ap', label: 'hold AP', hint: 'range check · abductions + thumb cmc', min: 20, max: 500 },
  { key: 'hold_mcp', label: 'hold MCP', hint: 'range check · MCPs', min: 20, max: 500 },
  { key: 'hold_pip', label: 'hold PIP', hint: 'range check · PIPs + thumb dip', min: 20, max: 500 },
  { key: 'tension_current', label: 'tension', hint: 'held while you ratchet', min: 50, max: 1000 },
]

function pickCurrents(defaults?: Partial<GuidedCurrents> | null): GuidedCurrents {
  const out = { ...DEFAULT_CURRENTS }
  for (const key of Object.keys(DEFAULT_CURRENTS) as (keyof GuidedCurrents)[]) {
    const value = defaults?.[key]
    if (typeof value === 'number') out[key] = value
  }
  return out
}

function inBounds(value: number, field: { min: number; max: number }): boolean {
  return Number.isFinite(value) && value >= field.min && value <= field.max
}

function loadOverrides(family: string): Partial<GuidedCurrents> {
  try {
    const stored = JSON.parse(localStorage.getItem(overridesKey(family)) ?? 'null')
    if (stored && typeof stored === 'object') {
      return Object.fromEntries(
        CURRENT_FIELDS.filter((f) => inBounds(stored[f.key], f)).map((f) => [f.key, stored[f.key]]),
      )
    }
  } catch {
    /* unreadable: no overrides */
  }
  return {}
}

function saveOverrides(family: string, overrides: Partial<GuidedCurrents>): void {
  try {
    if (Object.keys(overrides).length) {
      localStorage.setItem(overridesKey(family), JSON.stringify(overrides))
    } else {
      localStorage.removeItem(overridesKey(family))
    }
  } catch {
    /* storage unavailable: the values just aren't remembered */
  }
}

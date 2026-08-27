// Calibrate on its own: the whole hand, or a per-joint subset. The API takes
// joint ids only — the finger chips here are pure frontend convenience that
// expand (same prefix grouping as EncoderPanel) to per-joint checkboxes.
// Also summarizes the per-joint calibration status from hand info.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { CalibrationRun, HandInfo, JointInfo } from '../../api/types'
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
  const [runs, setRuns] = useState<CalibrationRun[]>([])
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [redoWrist, setRedoWrist] = useState(false)
  // null = untouched: follow the first-time default (calibrate the sensors
  // only when some encoder-backed joint has no anchor yet).
  const [jointSensors, setJointSensors] = useState<boolean | null>(null)
  // Per-run calibration-current overrides; empty = the config.yaml value.
  const [calCurrentDraft, setCalCurrentDraft] = useState('')
  const [wristCurrentDraft, setWristCurrentDraft] = useState('')

  // Calibration history: fetched once, then again after each finished
  // calibrate run (the run just appended a record).
  const handledCalRun = useRef<string | null>(null)
  useEffect(() => {
    api
      .calibrationHistory()
      .then((r) => setRuns(r.runs))
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    if (
      operation?.kind === 'calibrate' &&
      !isOperationActive(operation) &&
      handledCalRun.current !== operation.run_id
    ) {
      handledCalRun.current = operation.run_id
      api
        .calibrationHistory()
        .then((r) => setRuns(r.runs))
        .catch(() => undefined)
    }
  }, [operation])

  // Latest rejected measured-ROM per joint, from the history — surfaced
  // where an accepted Δ is missing so no joint's delta is silently hidden.
  const rejectedRoms = useMemo(() => {
    const map = new Map<
      string,
      { deltaDeg: number; spanDeg: number; when: string }
    >()
    for (const run of runs) {
      for (const event of run.events) {
        if (event.event !== 'measured_rom_rejected' || !event.joint) continue
        if (!map.has(event.joint))
          map.set(event.joint, {
            // deviation_deg is at the lower hardstop; the Δ shown in the
            // joint status is measured minus configured travel = its negation.
            deltaDeg: -(event.deviation_deg ?? 0),
            spanDeg: event.span_deg ?? 0,
            when: run.finished_at,
          })
      }
    }
    return map
  }, [runs])

  const joints = useMemo(() => handInfo?.joints ?? [], [handInfo])
  const missingAnchors = handInfo?.calibration.missing_anchors ?? []
  const hasEncoderJoints = joints.some((j) => j.encoder_backed)
  const firstTimeSensors = missingAnchors.length > 0
  const sensorsOn = jointSensors ?? firstTimeSensors
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

  // Mirrors the backend bounds: 50 mA floor (below it the sweep stalls on
  // friction and records false limits), configured max_current ceiling.
  const maxCurrent = handInfo?.control.max_current ?? 2000
  const calDefault = handInfo?.calibration.calibration_current ?? null
  const wristDefault = handInfo?.calibration.wrist_calibration_current ?? null
  const parseCurrent = (
    draft: string,
  ): { value: number | null; valid: boolean } => {
    if (draft.trim() === '') return { value: null, valid: true }
    const value = parseInt(draft, 10)
    const valid = Number.isFinite(value) && value >= 50 && value <= maxCurrent
    return { value: valid ? value : null, valid }
  }
  const calCurrent = parseCurrent(calCurrentDraft)
  const wristCurrent = parseCurrent(wristCurrentDraft)
  const currentsValid = calCurrent.valid && wristCurrent.valid
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
        ...(hasEncoderJoints ? { calibrate_joint_sensors: sensorsOn } : {}),
        ...(calCurrent.value !== null && calCurrent.value !== calDefault
          ? { calibration_current: calCurrent.value }
          : {}),
        ...(wristCurrent.value !== null && wristCurrent.value !== wristDefault
          ? { wrist_calibration_current: wristCurrent.value }
          : {}),
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
          {hasEncoderJoints && (
            <>
              <label className="joint-check">
                <input
                  type="checkbox"
                  checked={sensorsOn}
                  onChange={(e) => setJointSensors(e.target.checked)}
                />
                Also calibrate the joint sensors
              </label>
              <p className="setup-option-hint">
                {firstTimeSensors
                  ? 'On because some joints have never had their sensor ' +
                    'reference recorded — the first calibration needs it.'
                  : 'Off by default: the sensor references survive a motor ' +
                    'recalibration. Tick it to re-record them (e.g. after ' +
                    're-mounting an encoder). Sliders in the 3D view offer a ' +
                    'per-joint manual alternative (Sensor Cal).'}
              </p>
            </>
          )}
          <div className="setup-card-row">
            <button
              className="btn btn-primary"
              disabled={gate.blocked || !currentsValid}
              title={
                gate.reason ??
                (!currentsValid
                  ? `calibration current must be 50..${maxCurrent} mA`
                  : undefined)
              }
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
                <span className="setup-section-title">Calibration current</span>
                <p className="setup-copy dim">
                  How hard the motors press into the hardstops during the
                  sweep. Lower is gentler on tendons and hardstops; too low
                  stalls on friction before the true stop and records a short
                  range. Applies to this run only — edit calibration_current
                  in config.yaml to make it permanent.
                </p>
                <div
                  style={{
                    display: 'flex',
                    gap: 14,
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    fontSize: 10,
                  }}
                >
                  <label
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                    }}
                  >
                    <span style={{ color: 'var(--dim)' }}>fingers</span>
                    <input
                      type="number"
                      min={50}
                      max={maxCurrent}
                      step={10}
                      value={calCurrentDraft}
                      placeholder={calDefault !== null ? String(calDefault) : ''}
                      onChange={(e) => setCalCurrentDraft(e.target.value)}
                      style={{
                        width: 62,
                        borderColor: calCurrent.valid
                          ? undefined
                          : 'var(--err)',
                      }}
                    />
                    <span style={{ color: 'var(--dim)' }}>mA</span>
                  </label>
                  {hasWrist && (
                    <label
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 5,
                      }}
                    >
                      <span style={{ color: 'var(--dim)' }}>wrist</span>
                      <input
                        type="number"
                        min={50}
                        max={maxCurrent}
                        step={10}
                        value={wristCurrentDraft}
                        placeholder={
                          wristDefault !== null ? String(wristDefault) : ''
                        }
                        onChange={(e) => setWristCurrentDraft(e.target.value)}
                        style={{
                          width: 62,
                          borderColor: wristCurrent.valid
                            ? undefined
                            : 'var(--err)',
                        }}
                      />
                      <span style={{ color: 'var(--dim)' }}>mA</span>
                    </label>
                  )}
                  {(calCurrentDraft || wristCurrentDraft) && (
                    <button
                      className="setup-clear"
                      onClick={() => {
                        setCalCurrentDraft('')
                        setWristCurrentDraft('')
                      }}
                    >
                      use config defaults
                    </button>
                  )}
                </div>
                {!currentsValid && (
                  <p
                    className="setup-option-hint"
                    style={{ color: 'var(--err)' }}
                  >
                    50..{maxCurrent} mA (the configured max_current caps it)
                  </p>
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
                  <span style={{ display: 'inline-flex', gap: 8 }}>
                    {joint.rom_delta != null ? (
                      <span
                        style={{
                          color:
                            Math.abs(joint.rom_delta) > 4
                              ? 'var(--warn)'
                              : 'var(--dim)',
                          fontSize: 10,
                        }}
                        title={
                          `measured travel ${joint.rom_delta >= 0 ? 'exceeds' : 'falls short of'} ` +
                          `the configured range by ${Math.abs(joint.rom_delta).toFixed(1)}° ` +
                          `(measured [${joint.rom_measured?.[0].toFixed(1)}, ${joint.rom_measured?.[1].toFixed(1)}]°` +
                          `, config [${joint.rom[0]}, ${joint.rom[1]}]°)`
                        }
                      >
                        Δ {joint.rom_delta >= 0 ? '+' : ''}
                        {joint.rom_delta.toFixed(1)}°
                      </span>
                    ) : rejectedRoms.has(joint.id) ? (
                      <span
                        style={{ color: 'var(--err)', fontSize: 10 }}
                        title={
                          `the last sweep measured ${rejectedRoms.get(joint.id)!.spanDeg.toFixed(1)}° of travel — ` +
                          `${Math.abs(rejectedRoms.get(joint.id)!.deltaDeg).toFixed(1)}° ` +
                          `${rejectedRoms.get(joint.id)!.deltaDeg >= 0 ? 'more' : 'less'} than the configured range, ` +
                          'beyond the ±8° sanity limit, so the measurement was rejected and the config range kept ' +
                          `(${rejectedRoms.get(joint.id)!.when}). ` +
                          'Check the hardstops and the joint_roms config entry, then recalibrate.'
                        }
                      >
                        Δ {rejectedRoms.get(joint.id)!.deltaDeg >= 0 ? '+' : ''}
                        {rejectedRoms.get(joint.id)!.deltaDeg.toFixed(1)}°
                        {' rejected'}
                      </span>
                    ) : joint.encoder_backed ? (
                      <span
                        style={{ color: 'var(--dimmer)', fontSize: 10 }}
                        title={
                          'no measured range recorded for this joint — the last sweep either predates ' +
                          'measured-ROM support or rejected the measurement before history logging existed. ' +
                          'Run Calibrate with the joint sensors on to measure it.'
                        }
                      >
                        Δ —
                      </span>
                    ) : null}
                    <span
                      className={`joint-status-mark ${mark.cls}`}
                      title={mark.title}
                    >
                      {mark.text}
                    </span>
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* The calibration log (with the hardstop chart) lives on the Stats
          view; the fetched runs still feed the joint-status deltas above. */}
      <RomFrameSection handInfo={handInfo} joints={joints} />
    </div>
  )
}

// Optional: lay the encoder-measured travel onto the config ROM with the
// delta split equally onto both ends, and use that frame for the joint
// estimation — so the operator can compare it against the classic frame.
function RomFrameSection({
  handInfo,
  joints,
}: {
  handInfo: HandInfo | null
  joints: JointInfo[]
}) {
  const [busy, setBusy] = useState(false)
  const [needReconnect, setNeedReconnect] = useState(false)
  const romFrame = handInfo?.rom_frame ?? null
  const measured = joints.filter((j) => j.rom_delta != null)
  if (romFrame === null || !joints.some((j) => j.encoder_backed)) return null

  const setFrame = async (centered: boolean) => {
    setBusy(true)
    try {
      const result = await api.setRomFrame(centered ? 'centered' : 'anchor')
      if (result.requires_reconnect) setNeedReconnect(true)
      useAppStore.getState().setHandInfo(await api.handInfo())
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="setup-advanced">
      <span className="setup-section-title">Measured range of motion</span>
      {measured.length === 0 ? (
        <p className="setup-copy dim">
          No measured ranges recorded yet — run Calibrate with the joint
          sensors on and the sweep also measures each joint's actual travel
          (shown as Δ in the joint status above).
        </p>
      ) : (
        <p className="setup-copy dim">
          {measured.length} joint{measured.length > 1 ? 's have' : ' has'} a
          measured range (Δ = measured minus configured travel, in the joint
          status above).
        </p>
      )}
      <label className="joint-check">
        <input
          type="checkbox"
          checked={romFrame === 'centered'}
          disabled={busy}
          onChange={(e) => void setFrame(e.target.checked)}
        />
        Use the measured range, centered on the config range, for estimation
      </label>
      <p className="setup-option-hint">
        On: each joint's Δ is added (or subtracted) half on each end of its
        configured range and the joint estimation runs in that frame. Off:
        the classic frame — the measured range is pinned to the configured
        upper end. Toggle freely to compare which tracks the real hand
        better.
      </p>
      {needReconnect && (
        <p className="setup-option-hint" style={{ color: 'var(--warn)' }}>
          The running feedback loop keeps its old frame until you reconnect
          (Dashboard → Reconnect, or the Reconnect button in Motor Control).
        </p>
      )}
    </div>
  )
}

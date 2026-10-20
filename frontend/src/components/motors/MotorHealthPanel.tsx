// Per-motor health table from the 1 Hz motors.telemetry topic (flows through
// the rAF stream store; a JSON compare keeps React renders at telemetry rate).
// The temperature column is the browser twin of scripts/stress_test.py's
// monitor: % of the family's rated max operating temp, with a 10-segment
// bar — green under 70%, yellow from 70%, red from 90%.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type {
  FaultBudgets,
  MotorFaultEntry,
  MotorRecovery,
  MotorsFaults,
} from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { Diagnosable } from '../common/Diagnosable'
import { Panel } from '../common/Panel'
import { MotorIssues } from './MotorIssues'
import { RebootButton } from './RebootButton'
import {
  currentClass,
  deriveMotorIssues,
  errorClass,
  issueToDiagnosis,
  sortIssues,
  tempClass,
  tempPct,
  type MotorIssue,
  ERROR_RECENT_S,
  TEMP_ERR_PCT,
  TEMP_WARN_PCT,
  trackClass,
} from './motorIssueRules'

// Rated max operating temperature fallback (XC330/XC430) until telemetry
// carries the value from the connected motor family.
const DEFAULT_MAX_TEMP_C = 70
const BAR_SEGMENTS = 10

function tempPctColor(pct: number): string {
  if (pct >= TEMP_ERR_PCT) return 'var(--err)'
  if (pct >= TEMP_WARN_PCT) return 'var(--warn)'
  return 'var(--ok)'
}

// The script's `█████░░░░░` bar, as 10 blocks.
function TempBar({ pct }: { pct: number }) {
  const filled = Math.round((Math.min(pct, 100) / 100) * BAR_SEGMENTS)
  const color = tempPctColor(pct)
  return (
    <span
      style={{ display: 'inline-flex', gap: 1, verticalAlign: 'middle' }}
      title={`${pct.toFixed(0)}% of the rated max operating temperature`}
    >
      {Array.from({ length: BAR_SEGMENTS }, (_, i) => (
        <span
          key={i}
          style={{
            width: 5,
            height: 9,
            background: i < filled ? color : 'var(--panel-border-strong)',
          }}
        />
      ))}
    </span>
  )
}

interface MotorRow {
  id: string
  temp: number | null
  current: number | null
  faults: MotorFaultEntry | null
}

function buildRows(
  temps: Record<string, number>,
  currents: Record<string, number>,
  faults: MotorsFaults | null,
): MotorRow[] {
  const ids = Array.from(
    new Set([
      ...Object.keys(temps),
      ...Object.keys(currents),
      ...Object.keys(faults?.motors ?? {}),
    ]),
  ).sort((a, b) => Number(a) - Number(b))
  return ids.map((id) => ({
    id,
    temp: temps[id] ?? null,
    current: currents[id] ?? null,
    faults: faults?.motors[id] ?? null,
  }))
}

// What the operator has to DO, not which bit is set — the bit names are in
// the tooltip. "POWER" and "HEAT" are different jobs; that is the whole point
// of showing this separately from the temperature column.
const HW_KIND_LABEL: Record<string, string> = {
  power: 'POWER',
  thermal: 'HEAT',
  load: 'JAM',
  encoder: 'ENCODER',
  unknown: 'FAULT',
}

// Hand-wide motor current ceiling (mA): editable here because this panel is
// where currents (and their ceiling-based coloring) live, and it works on
// every motors-capable hand — the Control Loop tuning row only exists on
// feedback-loop hands.
function MaxCurrentControl() {
  const maxCurrent = useAppStore((s) => s.control?.max_current ?? null)
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const setError = useAppStore((s) => s.setError)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  // Follow the backend value until the user starts typing a change.
  useEffect(() => {
    if (maxCurrent !== null) setDraft(String(maxCurrent))
  }, [maxCurrent])

  if (maxCurrent === null) return null
  const value = parseInt(draft, 10)
  const valid = Number.isFinite(value) && value > 0 && value <= 2000
  const dirty = valid && value !== maxCurrent

  const apply = () => {
    if (!dirty) return
    setBusy(true)
    void api
      .setMaxCurrent(value)
      .then(() => setError(null))
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false))
  }

  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10 }}
      title={
        'hand-wide motor current ceiling — lower is gentler and cooler, ' +
        'higher is stronger. Applies immediately; a reconnect restores the ' +
        'config.yaml value (edit max_current there to make it permanent).'
      }
    >
      <span style={{ color: 'var(--dim)' }}>max current</span>
      <input
        type="number"
        min={1}
        max={2000}
        step={10}
        value={draft}
        disabled={!motors || busy}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') apply()
        }}
        style={{ width: 62 }}
      />
      <span style={{ color: 'var(--dim)' }}>mA</span>
      <button
        className="btn btn-secondary"
        disabled={!motors || busy || !dirty}
        title={
          !valid
            ? '1–2000 mA'
            : dirty
              ? `set the ceiling to ${value} mA`
              : 'unchanged'
        }
        onClick={apply}
      >
        Set
      </button>
    </span>
  )
}

export function MotorHealthPanel() {
  const maxCurrent = useAppStore((s) => s.control?.max_current ?? null)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const [rows, setRows] = useState<MotorRow[]>([])
  const lastJson = useRef('')

  // Telemetry is keyed by motor id; a hot motor is only actionable once you
  // know which joint it drives.
  const jointOfMotor = useMemo(() => {
    const map = new Map<string, string>()
    for (const joint of joints ?? []) {
      if (joint.motor_id !== null && joint.motor_id !== undefined) {
        map.set(String(joint.motor_id), joint.id)
      }
    }
    return map
  }, [joints])

  const [maxTemp, setMaxTemp] = useState<number>(DEFAULT_MAX_TEMP_C)
  // What actually turns a motor off, read from the motors. null until the
  // first telemetry payload carries it.
  const [shutdownTemp, setShutdownTemp] = useState<number | null>(null)
  const budgets = useAppStore((state) => state.control?.fault_budgets ?? null)
  const [bus, setBus] = useState<MotorsFaults['bus'] | null>(null)
  useStreamFrame((frames) => {
    const next = buildRows(
      frames.motors.temps,
      frames.motors.currents,
      frames.motors.faults,
    )
    const json = JSON.stringify(next)
    if (json !== lastJson.current) {
      lastJson.current = json
      setRows(next)
      setBus(frames.motors.faults?.bus ?? null)
    }
    const rated = frames.motors.maxTempC
    if (rated !== null && rated !== maxTemp) setMaxTemp(rated)
    const shutdown = frames.motors.shutdownTemps
    if (shutdown && Object.keys(shutdown).length) {
      const lowest = Math.min(...Object.values(shutdown))
      if (Number.isFinite(lowest) && lowest !== shutdownTemp) {
        setShutdownTemp(lowest)
      }
    }
  })

  // Per-motor issues, derived once: the table above the grid renders them,
  // and each row's popover reuses the very same list.
  const issuesByMotor = useMemo(() => {
    const map = new Map<string, MotorIssue[]>()
    for (const row of rows) {
      map.set(
        row.id,
        deriveMotorIssues({
          motorId: row.id,
          joint: jointOfMotor.get(row.id) ?? null,
          temp: row.temp,
          current: row.current,
          faults: row.faults,
          maxTemp: shutdownTemp ?? maxTemp,
          maxCurrent,
        }),
      )
    }
    return map
  }, [rows, jointOfMotor, maxTemp, shutdownTemp, maxCurrent])

  const allIssues = useMemo(
    () => sortIssues([...issuesByMotor.values()].flat()),
    [issuesByMotor],
  )

  const peak = rows.reduce<number | null>(
    (best, row) =>
      row.temp === null ? best : Math.max(best ?? -Infinity, row.temp),
    null,
  )

  return (
    <Panel
      title="Motor Health"
      toolbar={
        <span style={{ display: 'inline-flex', gap: 14, alignItems: 'center' }}>
          <FaultBudgetsControl />
          <MaxCurrentControl />
        </span>
      }
    >
      {rows.length === 0 ? (
        <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
          no motor telemetry yet — appears at 1 Hz once motors are connected
        </div>
      ) : (
        <>
        <MotorIssues issues={allIssues} />
        <div style={{ fontSize: 10, color: 'var(--dimmer)', marginBottom: 4 }}>
          rated operating temp: {maxTemp.toFixed(0)}°C
          {shutdownTemp !== null && (
            <>
              {' · '}
              <span title="the motors' own Temperature Limit register — what actually de-energizes them. A motor runs past the rated figure above without stopping.">
                shuts off at {shutdownTemp.toFixed(0)}°C
              </span>
            </>
          )}
        </div>
        <table className="motor-table">
          <thead>
            <tr>
              <th>MOTOR</th>
              <th>JOINT</th>
              <th>TEMP °C</th>
              <th>%MAX</th>
              <th aria-label="temperature bar" />
              <th>CURRENT mA</th>
              <th title="failed bus transactions + overload reboots this session">
                ERRORS
              </th>
              <th title="latched hardware error: the motor answers the bus but will not energize until it is rebooted">
                FAULT
              </th>
              <th title="is the motor actually following its commanded target?">
                TRACK
              </th>
              <th title="recoveries orca_core has performed on this motor: load reboots / thermal recoveries">
                RECOV
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              // A hot or overloaded motor is clickable: the popover names
              // the joint and what to check. Same list the issues table
              // above renders, so the two can never disagree.
              const joint = jointOfMotor.get(row.id) ?? null
              const problems = (issuesByMotor.get(row.id) ?? []).map(
                issueToDiagnosis,
              )
              const hw = row.faults?.hw_error ?? null
              const recovery = row.faults?.recovery ?? null
              const faults = row.faults
              const tracking = faults?.tracking ?? null
              const idCell =
                problems.length > 0 ? (
                  <Diagnosable
                    diagnoses={problems}
                    label={`diagnose motor ${row.id}`}
                  >
                    <span
                      style={{
                        textDecoration: 'underline dotted',
                        textUnderlineOffset: 3,
                      }}
                      title="click to see what is wrong"
                    >
                      {row.id}
                    </span>
                  </Diagnosable>
                ) : (
                  row.id
                )
              const limit = shutdownTemp ?? maxTemp
              const pct = tempPct(row.temp, limit)
              return (
                <tr key={row.id}>
                  <td>{idCell}</td>
                  <td className="motor-joint">{joint ?? '--'}</td>
                  <td className={tempClass(row.temp, limit)}>
                    {row.temp === null ? '--' : row.temp.toFixed(1)}
                  </td>
                  <td
                    className={tempClass(row.temp, maxTemp)}
                    style={{ color: pct !== null ? tempPctColor(pct) : undefined }}
                  >
                    {pct === null ? '--' : `${pct.toFixed(0)}%`}
                  </td>
                  <td>{pct !== null && <TempBar pct={pct} />}</td>
                  <td className={currentClass(row.current, maxCurrent)}>
                    {row.current === null ? '--' : row.current.toFixed(1)}
                  </td>
                  <td
                    className={errorClass(faults)}
                    title={
                      faults && faults.errors + faults.overloads > 0
                        ? `${faults.errors} bus errors, ${faults.overloads} overloads` +
                          (faults.last_error
                            ? ` — last: ${faults.last_error}` +
                              (faults.last_error_age_s !== null
                                ? ` (${faults.last_error_age_s.toFixed(0)}s ago)`
                                : '')
                            : '')
                        : 'no bus errors this session'
                    }
                  >
                    {faults === null
                      ? '--'
                      : faults.errors + faults.overloads}
                  </td>
                  <td
                    className={hw ? 'err' : ''}
                    title={
                      hw
                        ? `${hw.headline}. ${hw.disabled_note} ${hw.advice}`
                        : 'no latched hardware error'
                    }
                  >
                    {hw ? (
                      <span className="fault-cell">
                        {HW_KIND_LABEL[hw.kind] ?? hw.kind.toUpperCase()}
                        <RebootButton id={row.id} needsCooling={hw.needs_cooling} />
                      </span>
                    ) : (
                      '--'
                    )}
                  </td>
                  <td
                    className={trackClass(faults)}
                    title={
                      tracking
                        ? tracking.following
                          ? `following its command` +
                            (tracking.stalls > 0
                              ? ` — but stalled ${tracking.stalls}× for ` +
                                `${tracking.stalled_total_s.toFixed(0)}s total this session`
                              : '')
                          : `NOT following — off by ` +
                            `${tracking.deviation_deg?.toFixed(1) ?? '?'}° for ` +
                            `${tracking.stall_s.toFixed(0)}s`
                        : 'no adherence data — needs torque on and a commanded target'
                    }
                  >
                    {tracking === null
                      ? '--'
                      : tracking.following
                        ? tracking.stalls > 0
                          ? `ok ·${tracking.stalls}`
                          : 'ok'
                        : `✗ ${tracking.deviation_deg?.toFixed(0) ?? '?'}° ${tracking.stall_s.toFixed(0)}s`}
                  </td>
                  <td
                    className={recovery?.given_up || recovery?.thermal_given_up
                      ? 'bad' : recovery?.cooling ? 'warn' : undefined}
                    title={recoveryTitle(recovery, budgets)}
                  >
                    {recovery === null || recovery === undefined
                      ? '--'
                      : recovery.cooling
                        ? 'cooling'
                        : recovery.load_reboots === 0 &&
                            recovery.thermal_recoveries === 0
                          ? recovery.faults > 0
                            ? `${recovery.faults} logged`
                            : 'ok'
                          : `${recovery.load_reboots} / ${recovery.thermal_recoveries}`}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {peak !== null && (
          <div
            style={{
              fontSize: 10,
              marginTop: 4,
              color: tempPctColor((peak / maxTemp) * 100),
            }}
          >
            peak {peak.toFixed(1)}°C ({((peak / maxTemp) * 100).toFixed(0)}% of
            rated max)
          </div>
        )}
        {bus !== null && bus.errors > 0 && (
          <div
            style={{
              fontSize: 10,
              marginTop: 4,
              color:
                bus.last_error_age_s !== null &&
                bus.last_error_age_s < ERROR_RECENT_S
                  ? 'var(--err)'
                  : 'var(--dim)',
            }}
            title="failed motor-bus transactions this session, across all motors"
          >
            bus: {bus.errors} error(s)
            {bus.last_error
              ? ` — last: ${bus.last_error}` +
                (bus.last_error_age_s !== null
                  ? ` (${bus.last_error_age_s.toFixed(0)}s ago)`
                  : '')
              : ''}
          </div>
        )}
        </>
      )}
    </Panel>
  )
}

// What orca_core has done to a motor, spelled out: the counts alone do not
// say whether it is still being recovered or has been given up on.
function recoveryTitle(
  recovery: MotorRecovery | null | undefined,
  budgets: FaultBudgets | null,
): string {
  if (!recovery) {
    return 'no recovery data yet — appears after the first fault poll'
  }
  if (recovery.given_up) {
    return (
      `left latched after ${recovery.load_reboots} load reboots: it kept ` +
      'overloading, so recovering it again would only hide the mechanical cause'
    )
  }
  if (recovery.thermal_given_up) {
    return `left latched after ${recovery.thermal_recoveries} thermal recoveries`
  }
  if (recovery.cooling) {
    return 'overheated and stopped — waiting for it to cool before the latch is cleared'
  }
  const budget = budgets?.giveup_after_reboots
  return [
    `${recovery.load_reboots} load reboot(s)` +
      (budget ? ` of ${budget} before it is left latched` : ''),
    `${recovery.thermal_recoveries} thermal recovery(s)`,
    `${recovery.faults} fault(s) seen, including ones that did not stop the motor`,
  ].join(' · ')
}

// Three thresholds, all per motor, all counting reboots. The thermal one is
// unlimited by default: a motor that has cooled can work again, and the wait
// is self-limiting because it does not come back until it has.
function FaultBudgetsControl() {
  const budgets = useAppStore((state) => state.control?.fault_budgets ?? null)
  const setError = useAppStore((state) => state.setError)
  const [busy, setBusy] = useState(false)

  if (!budgets) return null

  const send = (body: Parameters<typeof api.setFaultBudgets>[0]) => {
    setBusy(true)
    void api
      .setFaultBudgets(body)
      .then(() => setError(null))
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false))
  }

  const field = (
    label: string,
    hint: string,
    value: number,
    key: 'report_after_reboots' | 'giveup_after_reboots',
  ) => (
    <label
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
      title={hint}
    >
      <span style={{ color: 'var(--dim)' }}>{label}</span>
      <input
        type="number"
        min={1}
        max={100}
        value={value}
        disabled={busy}
        style={{ width: 42, fontSize: 10 }}
        onChange={(e) => {
          const next = parseInt(e.target.value, 10)
          if (Number.isFinite(next) && next >= 1) send({ [key]: next })
        }}
      />
    </label>
  )

  const thermal = budgets.thermal_giveup_after_reboots
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        fontSize: 10,
      }}
    >
      {field(
        'report at',
        'reboots of one motor before its repetition is called out prominently',
        budgets.report_after_reboots,
        'report_after_reboots',
      )}
      {field(
        'give up at',
        'load reboots of one motor before it is left latched instead of ' +
          'recovered — a joint that keeps stalling is a mechanical fault, and ' +
          'recovering it again only hides the cause',
        budgets.giveup_after_reboots,
        'giveup_after_reboots',
      )}
      <label
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
        title={
          'thermal recoveries before giving up. Blank means unlimited, the ' +
          'default: a motor that has cooled can work again, and the wait is ' +
          'self-limiting because it does not come back until it has cooled.'
        }
      >
        <span style={{ color: 'var(--dim)' }}>thermal</span>
        <input
          type="number"
          min={1}
          max={100}
          placeholder="∞"
          value={thermal ?? ''}
          disabled={busy}
          style={{ width: 42, fontSize: 10 }}
          onChange={(e) => {
            if (e.target.value === '') {
              send({ thermal_unlimited: true })
              return
            }
            const next = parseInt(e.target.value, 10)
            if (Number.isFinite(next) && next >= 1) {
              send({ thermal_giveup_after_reboots: next })
            }
          }}
        />
      </label>
    </span>
  )
}

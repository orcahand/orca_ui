// One place that decides what counts as a motor problem, so the issues table
// and the per-row diagnosis popovers can never disagree about it.
//
// Everything here is derived from the motors.faults and motors.telemetry
// payloads the slow tick already publishes — deciding something is wrong costs
// no extra bus traffic.

import type { MotorFaultEntry } from '../../api/types'
import type { Diagnosis } from '../common/Diagnosable'

export type IssueSeverity = 'error' | 'warning'

// A bus error this recent means the motor is failing right now, not history.
export const ERROR_RECENT_S = 60
// stress_test.py's temp_color thresholds, in % of rated max.
export const TEMP_WARN_PCT = 70
export const TEMP_ERR_PCT = 90
// Current tint kicks in near the configured max_current ceiling.
export const CURRENT_WARN_FRACTION = 0.8

export interface MotorIssue {
  motorId: string
  joint: string | null
  severity: IssueSeverity
  // Names the fault itself: the latched bits where there are any, so the
  // operator reads "overload + overheating" rather than a category.
  label: string
  // What was actually measured, in one line.
  detail: string
  // What to check, in the order worth trying.
  checks: string[]
  // A latched hardware fault is the only kind a reboot can clear.
  reboot: { needsCooling: boolean } | null
}

export interface MotorIssueInput {
  motorId: string
  joint: string | null
  temp: number | null
  current: number | null
  faults: MotorFaultEntry | null
  maxTemp: number
  maxCurrent: number | null
}

export function tempPct(temp: number | null, maxTemp: number): number | null {
  return temp === null || maxTemp <= 0 ? null : (temp / maxTemp) * 100
}

/** CSS class for a temperature cell: '' | 'warn' | 'err'. */
export function tempClass(temp: number | null, maxTemp: number): string {
  const pct = tempPct(temp, maxTemp)
  if (pct === null) return ''
  if (pct >= TEMP_ERR_PCT) return 'err'
  if (pct >= TEMP_WARN_PCT) return 'warn'
  return ''
}

/** CSS class for a current cell: '' | 'warn' | 'err'. */
export function currentClass(
  current: number | null,
  maxCurrent: number | null,
): string {
  if (current === null || maxCurrent === null || maxCurrent <= 0) return ''
  const load = Math.abs(current) / maxCurrent
  if (load >= 1) return 'err'
  if (load >= CURRENT_WARN_FRACTION) return 'warn'
  return ''
}

/** CSS class for the bus-error count cell: '' | 'warn' | 'err'. */
export function errorClass(faults: MotorFaultEntry | null): string {
  if (!faults) return ''
  if (faults.errors + faults.overloads === 0) return ''
  const age = faults.last_error_age_s
  return age !== null && age < ERROR_RECENT_S ? 'err' : 'warn'
}

/** CSS class for the tracking cell: '' | 'warn' | 'err'. */
export function trackClass(faults: MotorFaultEntry | null): string {
  const tracking = faults?.tracking
  if (!tracking) return ''
  if (!tracking.following) return 'err'
  return tracking.stalls > 0 ? 'warn' : ''
}

/**
 * Everything currently wrong with one motor, worst first.
 *
 * A latched fault leads: the motor is not moving at all, which makes every
 * other reading about it beside the point.
 */
export function deriveMotorIssues(input: MotorIssueInput): MotorIssue[] {
  const { motorId, joint, temp, current, faults, maxTemp, maxCurrent } = input
  const issues: MotorIssue[] = []

  const hw = faults?.hw_error ?? null
  if (hw) {
    const flags = hw.flags.length > 0 ? hw.flags.join(' + ') : hw.kind
    issues.push({
      motorId,
      joint,
      severity: 'error',
      label: flags,
      detail: hw.headline,
      checks: [
        hw.disabled_note,
        hw.advice,
        ...(hw.needs_cooling
          ? []
          : ['this is not a heat fault — waiting will not clear it']),
      ],
      reboot: { needsCooling: hw.needs_cooling },
    })
  }

  const heat = tempClass(temp, maxTemp)
  if (heat) {
    const pct = tempPct(temp, maxTemp)!
    issues.push({
      motorId,
      joint,
      severity: heat === 'err' ? 'error' : 'warning',
      label: heat === 'err' ? 'overheating' : 'running hot',
      detail: `${temp!.toFixed(1)} °C — ${pct.toFixed(0)}% of the ${maxTemp.toFixed(0)}°C rating`,
      checks: [
        'give it a rest — motors shed heat slowly inside the palm',
        'check the joint for mechanical binding or over-tensioned tendons',
        'consider a lower max current (Motors → Control Loop)',
      ],
      reboot: null,
    })
  }

  const load = currentClass(current, maxCurrent)
  if (load) {
    issues.push({
      motorId,
      joint,
      severity: load === 'err' ? 'error' : 'warning',
      label: load === 'err' ? 'at current ceiling' : 'near current ceiling',
      detail: `${current!.toFixed(0)} mA of the ${maxCurrent!.toFixed(0)} mA ceiling`,
      checks: [
        'check for a jammed or obstructed joint',
        'check tendon tension — an over-tensioned tendon loads the motor at rest',
        'sustained high current is what overheats motors',
      ],
      reboot: null,
    })
  }

  const bus = errorClass(faults)
  if (faults && bus) {
    const age = faults.last_error_age_s
    issues.push({
      motorId,
      joint,
      severity: bus === 'err' ? 'error' : 'warning',
      label: 'bus errors',
      detail:
        `${faults.errors} failed transaction(s), ${faults.overloads} overload reboot(s) this session` +
        (faults.last_error
          ? ` — last: ${faults.last_error}` +
            (age !== null ? ` (${age.toFixed(0)}s ago)` : '')
          : ''),
      checks: [
        '"Port is in use" bursts mean another process or thread is holding the serial bus — close other tools using the port',
        '"no status packet" means the motor did not answer — check power and the daisy-chain cabling up to this motor',
        'overload reboots mean the motor hit its torque limit — check for jams and over-tensioned tendons',
      ],
      reboot: null,
    })
  }

  const tracking = faults?.tracking ?? null
  if (tracking && !tracking.following) {
    issues.push({
      motorId,
      joint,
      severity: 'error',
      label: 'not following',
      detail:
        `off by ${tracking.deviation_deg?.toFixed(1) ?? '?'}° for ` +
        `${tracking.stall_s.toFixed(0)}s ` +
        `(${tracking.stalls} stall(s), ${tracking.stalled_total_s.toFixed(0)}s total this session)`,
      checks: [
        'a latched hardware error stops the motor from energizing — see the FAULT column; only a reboot or power cycle clears it, torque toggling does not',
        'check the tendon: slack or snapped tendons move the motor without moving the joint',
        'check for mechanical jams or a joint blocked at its limit',
      ],
      reboot: null,
    })
  }

  return issues
}

/** The popover form of an issue, for the per-row Diagnosable. */
export function issueToDiagnosis(issue: MotorIssue): Diagnosis {
  return {
    subject: `motor ${issue.motorId}${issue.joint ? ` (${issue.joint})` : ''}`,
    state: `${issue.label} — ${issue.detail}`,
    ok: false,
    checks: issue.checks,
  }
}

/** Errors before warnings, then by motor id. */
export function sortIssues(issues: MotorIssue[]): MotorIssue[] {
  return [...issues].sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === 'error' ? -1 : 1
    return Number(a.motorId) - Number(b.motorId)
  })
}

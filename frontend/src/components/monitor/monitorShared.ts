// Shared bits of the electrical monitor, fused into the dashboard panels
// (browser twin of orca_core's scripts/monitor_sensors.py) — the verdict
// palette plus the click-to-diagnose explanations for every electrical
// subsystem: what a state means and what to physically check.

import type {
  EncoderJointHealth,
  EncoderVerdict,
  SensingLinkHealth,
} from '../../api/types'
import type { Diagnosis } from '../common/Diagnosable'

export const VERDICT_COLOR: Record<EncoderVerdict, string> = {
  live: 'var(--ok)',
  parity: 'var(--warn)',
  'chip error': 'var(--err)',
  'no encoder': 'var(--dimmer)',
  'no frames': 'var(--dimmer)',
}

const ENCODER_CHECKS: Record<EncoderVerdict, string[]> = {
  live: [],
  'no frames': [
    'no encoder frames are reaching the UI at all — this is the stream, not just this joint',
    'check the encoder link: USB cable, port power, and that the sensing board is up',
    'Reconnect (Motors tab) once the link is back',
  ],
  parity: [
    'data from this slot arrives corrupted',
    "re-seat the encoder's cable at the connector board slot",
    'check the cable for damage or nearby interference',
  ],
  'chip error': [
    'the encoder chip reports an internal error — usually the magnet',
    'check the magnet is present, centered and at the right distance from the chip',
    'if the magnet is fine, the chip itself may be failing',
  ],
  'no encoder': [
    'the slot reads a constant value — encoder dead or unwired',
    'check its wiring at the connector board',
    'the joint runs open-loop until it reads again — recalibrate after fixing',
  ],
}

export function encoderDiagnosis(
  joint: string,
  health: EncoderJointHealth,
  // Set when the backend currently distrusts this sensor and drops its
  // measured values (fallback to the motor estimate).
  suppressedReason?: string | null,
  restoreAfterS?: number,
): Diagnosis {
  const recovering = suppressedReason != null && health.verdict === 'live'
  const checks = [...(ENCODER_CHECKS[health.verdict] ?? [])]
  if (suppressedReason != null) {
    checks.unshift(
      'its measured values are currently DROPPED — the 3D model and joint ' +
        'displays use the motor estimate instead',
    )
    if (recovering) {
      checks.push(
        `reading clean right now — tracking returns after ~${restoreAfterS ?? 5}s ` +
          'of consecutively clean data',
      )
    }
  }
  return {
    subject: `${joint} joint sensor (slot ${health.slot})`,
    state: recovering ? 'suppressed (recovering)' : health.verdict,
    ok: health.verdict === 'live' && suppressedReason == null,
    reason: recovering ? `was: ${suppressedReason}` : health.reason,
    checks,
  }
}

export function tactileDiagnosis(
  finger: string,
  connected: boolean,
  taxels?: number,
): Diagnosis {
  return {
    subject: `${finger} tactile sensor`,
    state: connected ? 'connected' : 'not connected',
    ok: connected,
    reason: connected && taxels ? `${taxels} taxels reporting` : null,
    checks: connected
      ? []
      : [
          "check the finger's flex cable into the palm sensor board",
          're-seat both ends of the connector',
          'still down? swap cables with a working finger to isolate cable vs board',
        ],
  }
}

export function linkDiagnosis(
  name: string,
  link: SensingLinkHealth,
): Diagnosis {
  if (link.port_dead) {
    return {
      subject: `${name} link`,
      state: 'port dead',
      ok: false,
      reason: link.port_error,
      checks: [
        'the serial port vanished mid-session — USB unplug or power loss',
        'check the USB cable and hub power',
        'Reconnect (Motors tab) once the port re-enumerates',
      ],
    }
  }
  if (!link.connected) {
    return {
      subject: `${name} link`,
      state: 'down',
      ok: false,
      checks: [
        'no serial connection on this link',
        'check the cable and that the board shows up as a port',
        'Reconnect after fixing',
      ],
    }
  }
  const dirty = link.resyncs > 0 || link.bad_lrc > 0
  return {
    subject: `${name} link`,
    state: dirty ? 'noisy' : 'clean',
    ok: !dirty,
    reason: dirty
      ? `${link.resyncs} framing resyncs, ${link.bad_lrc} checksum errors`
      : null,
    checks: dirty
      ? [
          'framing/checksum errors mean a noisy line, not a dead one',
          'check cable quality and length, and separation from motor power wiring',
          'counters reset on reconnect — rising numbers are the problem, not old ones',
        ]
      : [],
  }
}

export function motorDiagnosis(
  motorId: string,
  joint: string | null,
  answering: boolean,
): Diagnosis {
  return {
    subject: `motor ${motorId}${joint ? ` (${joint})` : ''}`,
    state: answering ? 'answering' : 'not answering',
    ok: answering,
    checks: answering
      ? []
      : [
          'the motor answers no telemetry reads on the bus',
          'check the daisy-chain cable into this motor — upstream connections first',
          'check motor power; a latched hardware error shows in Direct motor control',
          'power-cycle + Reconnect clears latched errors',
        ],
  }
}

// Thermal thresholds as a fraction of the motor family's rated max operating
// temperature, matching MotorHealthPanel's bar colours.
export const TEMP_WARN_FRACTION = 0.7
export const TEMP_ERR_FRACTION = 0.9

export function thermalDiagnosis(
  motorId: string,
  joint: string | null,
  tempC: number,
  maxTempC: number,
): Diagnosis {
  const pct = Math.round((100 * tempC) / maxTempC)
  const hot = tempC >= maxTempC * TEMP_ERR_FRACTION
  return {
    subject: `motor ${motorId}${joint ? ` (${joint})` : ''}`,
    state: `${tempC.toFixed(0)} °C — ${pct}% of the ${maxTempC.toFixed(0)} °C rated max`,
    ok: false,
    checks: hot
      ? [
          'at the rated max the motor latches an overheating error and stops applying torque',
          'it keeps answering the bus and still acknowledges torque enable, so it looks alive while it does nothing',
          'stop driving it and let it cool; a power cycle clears the latch once cool',
          'a joint that stalls before its hardstop heats fastest — all the current becomes heat',
        ]
      : [
          'running warm; sustained load will reach the latch threshold',
          'lower max current, or give the hand idle time between runs',
        ],
  }
}

// Persistent calibration log: every run's raw events, read back from
// calibration_history.jsonl (stored next to calibration.yaml). Leads with a
// magnet-position table comparing the raw hardstop counts across runs, so an
// encoder magnet that drifts (loosens, slips on its shaft) shows up as a
// growing count offset at the same physical hardstop.

import { useMemo, useState } from 'react'
import type {
  CalibrationEvent,
  CalibrationRun,
  SensorFrameEntry,
} from '../../api/types'
import { CalibrationDeltaChart } from './CalibrationDeltaChart'
import { CalibrationRomChart } from './CalibrationRomChart'

const COUNTS_PER_REV = 16384
const LSB_DEG = 360 / COUNTS_PER_REV
// A hardstop re-measured this many degrees away from last time is suspect.
const DRIFT_WARN_DEG = 1.0

// Wrap-aware signed difference between two absolute magnet counts.
function countDrift(now: number, before: number): number {
  const raw = (((now - before) % COUNTS_PER_REV) + COUNTS_PER_REV) %
    COUNTS_PER_REV
  return raw > COUNTS_PER_REV / 2 ? raw - COUNTS_PER_REV : raw
}

interface MagnetSample {
  flex: number
  extend: number
  when: string
}

// Newest-first per joint: the raw counts sampled at both hardstops each time
// the sweep measured them (accepted or rejected — the magnets were read
// either way).
function magnetHistory(runs: CalibrationRun[]): Map<string, MagnetSample[]> {
  const map = new Map<string, MagnetSample[]>()
  for (const run of runs) {
    for (const event of run.events) {
      if (
        (event.event === 'measured_rom_recorded' ||
          event.event === 'measured_rom_rejected') &&
        event.joint &&
        event.flex_count != null &&
        event.extend_count != null
      ) {
        if (!map.has(event.joint)) map.set(event.joint, [])
        map.get(event.joint)!.push({
          flex: event.flex_count,
          extend: event.extend_count,
          when: run.finished_at,
        })
      }
    }
  }
  return map
}

function fmtDrift(now: number, before: number) {
  const counts = countDrift(now, before)
  const deg = counts * LSB_DEG
  return {
    text: `${counts >= 0 ? '+' : ''}${counts} cts (${deg >= 0 ? '+' : ''}${deg.toFixed(2)}°)`,
    warn: Math.abs(deg) > DRIFT_WARN_DEG,
  }
}

function fmtWhen(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function fmtClock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString()
}

function fmtEvent(event: CalibrationEvent): string {
  const magnets =
    event.flex_count != null && event.extend_count != null
      ? ` · magnets flex@${event.flex_count} extend@${event.extend_count}`
      : ''
  switch (event.event) {
    case 'calibration_started':
      return `started: ${event.steps} steps${
        Array.isArray(event.joints) ? ` (${event.joints.join(', ')})` : ''
      }`
    case 'step_started':
      return `step ${(event.index ?? 0) + 1}/${event.total}: ${Object.entries(
        (event.joints as Record<string, string>) ?? {},
      )
        .map(([joint, dir]) => `${joint} ${dir}`)
        .join(', ')}`
    case 'joint_calibrated':
      return `${event.joint} calibrated (ratio ${event.ratio?.toFixed(4)})`
    case 'encoder_anchor_recorded':
      return (
        `${event.joint} anchor magnet @ ${event.anchor_count} counts ` +
        `(flex hardstop, ${event.anchor_angle_deg?.toFixed(1)}°)`
      )
    case 'encoder_anchor_failed':
      return `${event.joint} anchor FAILED: ${event.error}`
    case 'measured_rom_recorded':
      return (
        `${event.joint} measured ROM [${event.rom?.[0]?.toFixed(1)}, ` +
        `${event.rom?.[1]?.toFixed(1)}]° ` +
        `(Δ ${(event.deviation_deg ?? 0) >= 0 ? '+' : ''}` +
        `${event.deviation_deg?.toFixed(1)}° at the lower hardstop)${magnets}`
      )
    case 'measured_rom_rejected':
      return (
        `${event.joint} measured ROM REJECTED: span ` +
        `${event.span_deg?.toFixed(1)}° puts the lower hardstop ` +
        `${(event.deviation_deg ?? 0) >= 0 ? '+' : ''}` +
        `${event.deviation_deg?.toFixed(1)}° off config — config kept${magnets}`
      )
    case 'wrist_skipped':
      return 'wrist already calibrated — skipped'
    case 'calibration_done':
      return 'calibration complete'
    case 'calibration_aborted':
      return 'aborted — completed steps persisted'
    default:
      return JSON.stringify(event)
  }
}

export function CalibrationLogSection({
  runs,
  frame,
}: {
  runs: CalibrationRun[]
  frame?: Record<string, SensorFrameEntry>
}) {
  const [open, setOpen] = useState(false)
  const magnets = useMemo(() => magnetHistory(runs), [runs])
  if (runs.length === 0) return null

  const magnetRows = [...magnets.entries()]
  return (
    <div className="setup-advanced">
      <button
        className="setup-expander"
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        {open ? '▾' : '▸'} Calibration log
        <span className="setup-summary">
          {' '}
          · {runs.length} run{runs.length > 1 ? 's' : ''}, latest{' '}
          {fmtWhen(runs[0].finished_at)}
        </span>
      </button>
      {open && (
        <>
          <p className="setup-copy dim">
            Every calibration run is archived to calibration_history.jsonl
            next to calibration.yaml — including the raw magnet counts read
            at each joint's two hardstops. The same hardstop re-measuring at
            a different count means the encoder magnet (or the hardstop)
            moved.
          </p>
          <CalibrationRomChart runs={runs} frame={frame} />
          <CalibrationDeltaChart runs={runs} />
          {magnetRows.length > 0 && (
            <table className="traj-table" style={{ fontSize: 10 }}>
              <thead>
                <tr>
                  <th>joint</th>
                  <th>flex hardstop</th>
                  <th>extend hardstop</th>
                  <th>drift vs previous run</th>
                </tr>
              </thead>
              <tbody>
                {magnetRows.map(([joint, samples]) => {
                  const [latest, previous] = samples
                  const flexDrift = previous
                    ? fmtDrift(latest.flex, previous.flex)
                    : null
                  const extendDrift = previous
                    ? fmtDrift(latest.extend, previous.extend)
                    : null
                  return (
                    <tr key={joint}>
                      <td>{joint}</td>
                      <td title={`sampled ${fmtWhen(latest.when)}`}>
                        {latest.flex} cts
                      </td>
                      <td title={`sampled ${fmtWhen(latest.when)}`}>
                        {latest.extend} cts
                      </td>
                      <td
                        style={{
                          color:
                            flexDrift?.warn || extendDrift?.warn
                              ? 'var(--warn)'
                              : 'var(--dim)',
                        }}
                        title={
                          previous
                            ? `previous sample ${fmtWhen(previous.when)}`
                            : 'only one measurement so far — drift needs two'
                        }
                      >
                        {flexDrift && extendDrift
                          ? `flex ${flexDrift.text} · ext ${extendDrift.text}`
                          : '— first measurement'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {runs.map((run) => (
            <details key={run.started_at} style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 10 }}>
                {fmtWhen(run.started_at)} ·{' '}
                {run.joints === null ? 'full hand' : run.joints.join(', ')}
                {run.force_wrist ? ' · wrist forced' : ''}
                {run.anchor_pass ? ' · joint sensors' : ''} ·{' '}
                {run.completed ? (
                  <span style={{ color: 'var(--ok)' }}>✓ completed</span>
                ) : (
                  <span style={{ color: 'var(--err)' }}>
                    ✕ {run.error ?? 'aborted'}
                  </span>
                )}
              </summary>
              <div style={{ padding: '4px 0 4px 14px' }}>
                {run.events
                  .filter((event) => event.event !== 'step_done')
                  .map((event, index) => (
                    <div
                      key={index}
                      style={{ fontSize: 10, color: 'var(--dim)' }}
                    >
                      <span style={{ color: 'var(--dimmer)' }}>
                        {fmtClock(event.t)}
                      </span>{' '}
                      {fmtEvent(event)}
                    </div>
                  ))}
              </div>
            </details>
          ))}
        </>
      )}
    </div>
  )
}

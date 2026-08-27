// Stats tab: lifetime joint-usage telemetry, organized into user-managed
// sessions (persisted in joint_usage.json next to calibration.yaml — this
// computer, this hand). Motion stats accrue ONLY while joints actually
// travel: a hand that is merely on — torque enabled, holding a commanded
// pose — accumulates nothing. Sensor health (encoder verdicts, tactile
// finger connections, links, motor bus) is watched whenever the hand is
// connected: transitions become events, unhealthy time is accumulated.
// Sessions can be created, renamed and deleted; "All sessions" stitches
// them into the lifetime total. The calibration log lives here too.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type {
  CalibrationRun,
  JointUsage,
  UsageHealth,
  SensorFrameEntry,
  UsageSession,
  UsageSnapshot,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { CalibrationLogSection } from '../setup/CalibrationLogSection'

const REFRESH_S = 5
const ALL = '__all__'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

function fmtDuration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`
  if (seconds < 5400) return `${(seconds / 60).toFixed(0)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

// Sessions are auto-named at creation ("session N"); the date fallback only
// covers records from before auto-naming existed.
function sessionName(session: UsageSession): string {
  return session.label ?? fmtWhen(session.started_at)
}

// ----- stitching -------------------------------------------------------------

function mergeJoint(into: JointUsage, from: JointUsage): JointUsage {
  return {
    rom: into.rom,
    travel_deg: into.travel_deg + from.travel_deg,
    moving_s: into.moving_s + from.moving_s,
    observed_s: into.observed_s + from.observed_s,
    hist: into.hist.map((v, i) => v + (from.hist[i] ?? 0)),
    min_deg:
      into.min_deg === null
        ? from.min_deg
        : from.min_deg === null
          ? into.min_deg
          : Math.min(into.min_deg, from.min_deg),
    max_deg:
      into.max_deg === null
        ? from.max_deg
        : from.max_deg === null
          ? into.max_deg
          : Math.max(into.max_deg, from.max_deg),
    reversals: into.reversals + from.reversals,
    max_speed_dps: Math.max(into.max_speed_dps, from.max_speed_dps),
    first_seen: into.first_seen ?? from.first_seen,
    last_active: from.last_active ?? into.last_active,
  }
}

function stitch(sessions: UsageSession[]): {
  joints: Record<string, JointUsage>
  health: UsageHealth
} {
  const joints: Record<string, JointUsage> = {}
  const health: UsageHealth = {
    observed_s: 0,
    down_s: {},
    events: [],
    events_dropped: 0,
  }
  for (const session of sessions) {
    for (const [joint, stats] of Object.entries(session.joints)) {
      joints[joint] = joints[joint]
        ? mergeJoint(joints[joint], stats)
        : { ...stats, hist: [...stats.hist] }
    }
    health.observed_s += session.health.observed_s
    health.events_dropped += session.health.events_dropped
    health.events.push(...session.health.events)
    for (const [key, seconds] of Object.entries(session.health.down_s)) {
      health.down_s[key] = (health.down_s[key] ?? 0) + seconds
    }
  }
  return { joints, health }
}

// ----- metric helpers --------------------------------------------------------

function romCycles(usage: JointUsage): number {
  const span = usage.rom[1] - usage.rom[0]
  return span > 0 ? usage.travel_deg / (2 * span) : 0
}

function hardstopShare(usage: JointUsage): number | null {
  if (usage.observed_s <= 0 || usage.hist.length < 2) return null
  const edge = usage.hist[0] + usage.hist[usage.hist.length - 1]
  return (edge / usage.observed_s) * 100
}

// Share of the monitored time the joint's encoder read healthy, in percent.
// High precision on purpose: at 5 decimals a single ~1 s dropout stays
// visible even after hundreds of hours of uptime.
function sensorUptimePct(health: UsageHealth, joint: string): number | null {
  if (health.observed_s <= 0) return null
  const down = health.down_s[`encoder:${joint}`] ?? 0
  return (Math.max(health.observed_s - down, 0) / health.observed_s) * 100
}

function uptimeColor(pct: number): string | undefined {
  if (pct >= 99.9) return 'var(--ok)'
  return pct >= 99 ? 'var(--warn)' : 'var(--err)'
}

function healthSubject(key: string): string {
  if (key === 'motors') return 'motor bus'
  const [kind, name] = key.split(':', 2)
  if (kind === 'encoder') return `${name} joint sensor`
  if (kind === 'tactile') return `${name} tactile`
  if (kind === 'link') return `${name} link`
  return key
}

// ----- tiny visuals ----------------------------------------------------------

function Histogram({ usage }: { usage: JointUsage }) {
  const peak = Math.max(...usage.hist, 1e-9)
  const width = 96
  const height = 18
  const barWidth = width / usage.hist.length
  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label="time spent per angle while moving"
    >
      {usage.hist.map((seconds, index) => {
        const h = seconds > 0 ? Math.max((seconds / peak) * height, 1) : 0
        return (
          <rect
            key={index}
            x={index * barWidth}
            y={height - h}
            width={Math.max(barWidth - 0.5, 0.5)}
            height={h}
            fill="rgb(var(--accent-rgb) / 0.8)"
          >
            <title>
              {`${(
                usage.rom[0] +
                ((usage.rom[1] - usage.rom[0]) * index) / usage.hist.length
              ).toFixed(0)}°…${(
                usage.rom[0] +
                ((usage.rom[1] - usage.rom[0]) * (index + 1)) /
                  usage.hist.length
              ).toFixed(0)}°: ${fmtDuration(seconds)}`}
            </title>
          </rect>
        )
      })}
    </svg>
  )
}

function RangeBar({ usage }: { usage: JointUsage }) {
  const [lower, upper] = usage.rom
  const span = upper - lower
  if (span <= 0 || usage.min_deg === null || usage.max_deg === null)
    return <span style={{ color: 'var(--dimmer)' }}>—</span>
  const from = Math.min(Math.max((usage.min_deg - lower) / span, 0), 1)
  const to = Math.min(Math.max((usage.max_deg - lower) / span, 0), 1)
  const coverage = ((to - from) * 100).toFixed(0)
  return (
    <span
      title={
        `visited ${usage.min_deg.toFixed(1)}°…${usage.max_deg.toFixed(1)}° ` +
        `of the configured [${lower}°, ${upper}°] (${coverage}% of the ROM)`
      }
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
    >
      <svg width={72} height={8}>
        <rect
          x={0}
          y={3}
          width={72}
          height={2}
          fill="var(--dimmer)"
          opacity={0.4}
        />
        <rect
          x={from * 72}
          y={1}
          width={Math.max((to - from) * 72, 1)}
          height={6}
          fill="rgb(var(--accent-rgb) / 0.9)"
        />
      </svg>
      <span style={{ color: 'var(--dim)' }}>{coverage}%</span>
    </span>
  )
}

// ----- sensor health section -------------------------------------------------

function HealthSection({ health }: { health: UsageHealth }) {
  const downtime = Object.entries(health.down_s).sort((a, b) => b[1] - a[1])
  const events = [...health.events].reverse()
  return (
    <div style={{ marginTop: 4 }}>
      {downtime.length === 0 && events.length === 0 ? (
        <p className="setup-copy dim">
          no sensor problems recorded
          {health.observed_s > 0 &&
            ` in ${fmtDuration(health.observed_s)} of monitoring`}{' '}
          — joint sensors, tactile fingers, sensing links and the motor bus
          all stayed healthy.
        </p>
      ) : (
        <>
          {downtime.length > 0 && (
            <table className="traj-table" style={{ fontSize: 10 }}>
              <thead>
                <tr>
                  <th>sensor</th>
                  <th>unhealthy for</th>
                  <th title="share of the monitored time">of monitored</th>
                </tr>
              </thead>
              <tbody>
                {downtime.map(([key, seconds]) => (
                  <tr key={key}>
                    <td>{healthSubject(key)}</td>
                    <td style={{ color: 'var(--warn)' }}>
                      {fmtDuration(seconds)}
                    </td>
                    <td style={{ color: 'var(--dim)' }}>
                      {health.observed_s > 0
                        ? `${((seconds / health.observed_s) * 100).toFixed(1)}%`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {events.length > 0 && (
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 10 }}>
                {events.length} health event{events.length > 1 ? 's' : ''}
                {health.events_dropped > 0 &&
                  ` (+${health.events_dropped} dropped)`}
              </summary>
              <div style={{ padding: '4px 0 4px 14px' }}>
                {events.map((event, index) => (
                  <div
                    key={index}
                    style={{ fontSize: 10, color: 'var(--dim)' }}
                  >
                    <span style={{ color: 'var(--dimmer)' }}>
                      {fmtWhen(event.t)}
                    </span>{' '}
                    {healthSubject(event.subject)}:{' '}
                    {event.from ?? 'unknown'} →{' '}
                    <span
                      style={{
                        color:
                          event.to === 'up' || event.to === 'live'
                            ? 'var(--ok)'
                            : 'var(--err)',
                      }}
                    >
                      {event.to}
                    </span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  )
}

// ----- the view --------------------------------------------------------------

export function StatsView() {
  const handJoints = useAppStore((s) => s.handInfo?.joints)
  const [usage, setUsage] = useState<UsageSnapshot | null>(null)
  const [runs, setRuns] = useState<CalibrationRun[]>([])
  const [frame, setFrame] = useState<Record<string, SensorFrameEntry>>({})
  const [selected, setSelected] = useState<string>(ALL)

  const load = () =>
    api
      .usageStats()
      .then(setUsage)
      .catch(() => undefined)

  useEffect(() => {
    load()
    api
      .calibrationHistory()
      .then((r) => {
        setRuns(r.runs)
        setFrame(r.frame ?? {})
      })
      .catch(() => undefined)
    const timer = window.setInterval(load, REFRESH_S * 1000)
    return () => window.clearInterval(timer)
  }, [])

  const sessions = usage?.sessions ?? []
  const selectedSession =
    selected === ALL ? null : sessions.find((s) => s.id === selected)
  // A deleted selection falls back to the stitched view.
  useEffect(() => {
    if (selected !== ALL && usage && !selectedSession) setSelected(ALL)
  }, [usage, selected, selectedSession])

  // Which joints have an encoder at all — a joint without one gets no uptime
  // figure rather than a misleading 100%. Falls back to the health record
  // (any logged downtime proves a sensor exists) when no hand is connected.
  const encoderJoints = useMemo(
    () =>
      new Set(
        (handJoints ?? []).filter((j) => j.encoder_backed).map((j) => j.id),
      ),
    [handJoints],
  )

  const { joints: jointMap, health } = selectedSession
    ? { joints: selectedSession.joints, health: selectedSession.health }
    : stitch(sessions)
  const joints = Object.entries(jointMap)
  const totalTravel = joints.reduce((sum, [, j]) => sum + j.travel_deg, 0)
  const inMotion = joints.reduce((max, [, j]) => Math.max(max, j.moving_s), 0)
  const busiest = joints.reduce(
    (best: [string, JointUsage] | null, entry) =>
      best === null || entry[1].travel_deg > best[1].travel_deg
        ? entry
        : best,
    null,
  )

  const newSession = () => {
    const label =
      window.prompt(
        'Name for the new session (leave empty for an automatic name — ' +
          'you can rename it later):',
        '',
      ) ?? undefined
    void api
      .usageNewSession(label || undefined)
      .then((r) => {
        setSelected(r.id)
        return load()
      })
      .catch(fail)
  }

  const renameSession = () => {
    if (!selectedSession) return
    const label = window.prompt(
      'New name for this session:',
      selectedSession.label ?? '',
    )
    if (label === null) return
    void api
      .usageRenameSession(selectedSession.id, label)
      .then(load)
      .catch(fail)
  }

  const deleteSession = () => {
    if (!selectedSession) return
    if (
      !window.confirm(
        `Delete session "${sessionName(selectedSession)}" and its stats? ` +
          'This cannot be undone.',
      )
    )
      return
    void api
      .usageDeleteSession(selectedSession.id)
      .then(() => {
        setSelected(ALL)
        return load()
      })
      .catch(fail)
  }

  const resetAll = () => {
    if (
      !window.confirm(
        'Delete ALL sessions and lifetime usage statistics for this hand? ' +
          'The history cannot be recovered.',
      )
    )
      return
    void api
      .usageReset()
      .then(() => {
        setSelected(ALL)
        return load()
      })
      .catch(fail)
  }

  return (
    <>
      <Panel
        title="Joint Usage"
        toolbar={
          <span style={{ display: 'inline-flex', gap: 6 }}>
            <button
              className="btn btn-primary"
              title="close the running session and start a fresh one (old sessions are kept)"
              onClick={newSession}
            >
              + New session
            </button>
            {selectedSession && (
              <>
                <button className="btn btn-secondary" onClick={renameSession}>
                  Rename
                </button>
                <button
                  className="btn btn-danger"
                  title="delete this session and its stats"
                  onClick={deleteSession}
                >
                  Delete
                </button>
              </>
            )}
            <button
              className="btn btn-danger"
              title="wipe every session — the full lifetime history"
              onClick={resetAll}
            >
              Reset all
            </button>
          </span>
        }
      >
        <div
          style={{
            display: 'flex',
            gap: 6,
            flexWrap: 'wrap',
            marginBottom: 8,
            alignItems: 'center',
          }}
        >
          <button
            className={`view-tab ${selected === ALL ? 'active' : ''}`}
            onClick={() => setSelected(ALL)}
            title="all sessions stitched together — the lifetime total"
          >
            All sessions
          </button>
          {sessions.map((session) => (
            <button
              key={session.id}
              className={`view-tab ${selected === session.id ? 'active' : ''}`}
              onClick={() => setSelected(session.id)}
              title={
                `${fmtWhen(session.started_at)} → ` +
                `${session.ended_at ? fmtWhen(session.ended_at) : 'now'}`
              }
            >
              {sessionName(session)}
              {session.id === usage?.current_id && (
                <span style={{ color: 'var(--ok)' }}> ●</span>
              )}
            </button>
          ))}
        </div>

        {usage === null || joints.length === 0 ? (
          <div className="panel-empty">
            nothing logged {selectedSession ? 'in this session ' : ''}yet —
            stats accumulate only while joints actually travel; a hand that
            is connected, torqued and holding still logs nothing
          </div>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                gap: 16,
                flexWrap: 'wrap',
                fontSize: 10,
                color: 'var(--dim)',
                marginBottom: 8,
              }}
            >
              <span>
                {selectedSession
                  ? `session ${sessionName(selectedSession)}`
                  : `${sessions.length} session${sessions.length > 1 ? 's' : ''} stitched`}
              </span>
              <span>
                in motion{' '}
                <span style={{ color: 'var(--text)' }}>
                  {fmtDuration(inMotion)}
                </span>
              </span>
              <span>
                total travel{' '}
                <span style={{ color: 'var(--text)' }}>
                  {Math.round(totalTravel).toLocaleString()}°
                </span>{' '}
                (≈{Math.round(totalTravel / 360).toLocaleString()} rev)
              </span>
              {busiest && (
                <span>
                  busiest joint{' '}
                  <span style={{ color: 'var(--text)' }}>{busiest[0]}</span>
                </span>
              )}
            </div>
            <table className="traj-table" style={{ fontSize: 10 }}>
              <thead>
                <tr>
                  <th>joint</th>
                  <th title="time-weighted histogram of where the joint operated WHILE moving">
                    where it moves
                  </th>
                  <th title="range actually visited vs the configured ROM">
                    range used
                  </th>
                  <th title="cumulative degrees moved (noise-deadbanded; holding still counts nothing)">
                    travel
                  </th>
                  <th title="equivalent full open-close cycles (travel ÷ 2×ROM)">
                    ≈cycles
                  </th>
                  <th title="time actually in motion">in motion</th>
                  <th title="direction changes — a proxy for tendon load cycles">
                    reversals
                  </th>
                  <th title="fastest observed movement">top speed</th>
                  <th title="share of active time in the outermost bins, next to a hardstop">
                    at hardstops
                  </th>
                  <th title="share of the monitored time this joint's sensor read healthy — high precision so even a single short dropout shows">
                    sensor uptime
                  </th>
                  <th>last active</th>
                </tr>
              </thead>
              <tbody>
                {joints.map(([joint, stats]) => {
                  const edge = hardstopShare(stats)
                  const hasSensor =
                    encoderJoints.has(joint) ||
                    `encoder:${joint}` in health.down_s
                  const uptime = hasSensor
                    ? sensorUptimePct(health, joint)
                    : null
                  return (
                    <tr key={joint}>
                      <td className="traj-name">{joint}</td>
                      <td>
                        <Histogram usage={stats} />
                      </td>
                      <td>
                        <RangeBar usage={stats} />
                      </td>
                      <td title={`${stats.travel_deg.toLocaleString()}°`}>
                        {Math.round(stats.travel_deg).toLocaleString()}°
                      </td>
                      <td>{Math.round(romCycles(stats)).toLocaleString()}</td>
                      <td
                        title={`active for ${fmtDuration(stats.observed_s)} in total`}
                      >
                        {fmtDuration(stats.moving_s)}
                      </td>
                      <td>{stats.reversals.toLocaleString()}</td>
                      <td>{Math.round(stats.max_speed_dps)}°/s</td>
                      <td
                        style={{
                          color:
                            edge !== null && edge > 25
                              ? 'var(--warn)'
                              : undefined,
                        }}
                      >
                        {edge === null ? '—' : `${edge.toFixed(0)}%`}
                      </td>
                      <td
                        style={{
                          color:
                            uptime === null ? undefined : uptimeColor(uptime),
                        }}
                        title={
                          uptime === null
                            ? 'no encoder on this joint, or nothing monitored yet'
                            : `sensor healthy for ${fmtDuration(
                                Math.max(
                                  health.observed_s -
                                    (health.down_s[`encoder:${joint}`] ?? 0),
                                  0,
                                ),
                              )} of ${fmtDuration(health.observed_s)} monitored` +
                              (health.down_s[`encoder:${joint}`]
                                ? ` (${fmtDuration(health.down_s[`encoder:${joint}`])} unhealthy)`
                                : '')
                        }
                      >
                        {uptime === null ? '—' : `${uptime.toFixed(5)}%`}
                      </td>
                      <td style={{ color: 'var(--dim)' }}>
                        {fmtWhen(stats.last_active)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="setup-copy dim" style={{ marginTop: 8 }}>
              Stored in {usage.path}. Only real joint motion counts: steps
              under 0.35° are sensor noise, and a joint parked under a
              standing position command accumulates nothing — commanded moves
              and physically posing the hand both do.
            </p>
          </>
        )}
      </Panel>

      <Panel title="Sensor Health">
        <p className="setup-copy dim">
          Watched whenever the hand is connected — idle included: per-joint
          encoder verdicts, tactile finger connections, sensing links and
          the motor bus. {selectedSession ? 'This session' : 'All sessions'}
          {health.observed_s > 0 &&
            ` · ${fmtDuration(health.observed_s)} monitored`}
          .
        </p>
        <HealthSection health={health} />
      </Panel>

      <Panel title="Calibration History">
        {runs.length === 0 ? (
          <div className="panel-empty">
            no calibration runs archived yet — the next calibration writes
            calibration_history.jsonl next to calibration.yaml
          </div>
        ) : (
          <CalibrationLogSection runs={runs} frame={frame} />
        )}
      </Panel>
    </>
  )
}

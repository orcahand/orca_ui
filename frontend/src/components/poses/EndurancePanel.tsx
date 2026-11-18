// Endurance: a looping replay counts its cycles, with each cycle's peak
// fingertip force and tactile health, on disk in the hand's folder. Every
// viewer sees the same record (the `endurance` topic, REST on reconnect), and
// it outlives Stop and a console restart.

import { useEffect, useState } from 'react'
import type { EnduranceRun, TipDrops } from '../../api/types'
import { useOperationStore } from '../../state/operationStore'
import { Panel } from '../common/Panel'

function endOf(run: EnduranceRun, now: number): number {
  if (run.ended_at) return run.ended_at
  if (run.state === 'running') return now
  return run.last_cycle_at ?? run.started_at
}

function duration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m ${s % 60}s`
}

function perHour(run: EnduranceRun, now: number): string {
  const hours = (endOf(run, now) - run.started_at) / 3600
  const played = run.cycles - (run.carried_cycles ?? 0)
  return hours > 0 && played ? (played / hours).toFixed(0) : '—'
}

function lastDrop(run: EnduranceRun, finger: string, now: number): string {
  const d = run.drops?.[finger]
  if (!d?.last_at) return '—'
  if (d.open_since) return `out for ${duration(now - d.open_since)}`
  return `${duration(now - d.last_at)} ago`
}

function dropsPerHour(run: EnduranceRun, finger: string, now: number): string {
  const hours = (endOf(run, now) - run.started_at) / 3600
  const count = run.drops?.[finger]?.count ?? 0
  // A rate over the first minutes says more about luck than the tip.
  return hours >= 1 / 6 ? (count / hours).toFixed(1) : '—'
}

function dropStats(d: TipDrops | undefined): string | undefined {
  if (!d?.count) return undefined
  const parts = []
  if (d.median_s !== null) parts.push(`lasted ${d.min_s}–${d.max_s} s, median ${d.median_s} s`)
  if (d.interval_mean_s !== null) parts.push(`every ${d.interval_mean_s} s on average`)
  if (d.interval_cv !== null)
    parts.push(d.interval_cv < 0.5 ? 'regular' : d.interval_cv > 1.5 ? 'in bursts' : 'at random')
  if (d.phase_p !== null)
    parts.push(
      d.phase_p < 0.05
        ? `gathered at ${Math.round((d.phase_peak ?? 0) * 100)}% of the cycle`
        : 'anywhere in the cycle',
    )
  return parts.join(' · ')
}

function outcome(run: EnduranceRun): string {
  if (run.state === 'running') return 'running'
  if (run.state === 'done') return `done after ${run.cycles}`
  return `${run.state} at cycle ${run.cycles}`
}

function started(run: EnduranceRun): string {
  return new Date(run.started_at * 1000).toLocaleString()
}

export function EndurancePanel() {
  const endurance = useOperationStore((s) => s.endurance)
  const current = endurance?.current ?? null
  const [clock, setNow] = useState(() => Date.now() / 1000)
  // Times come from the console's clock; this browser's may be off.
  const skew = useOperationStore((s) => s.enduranceSkew) ?? 0
  const now = clock + skew

  useEffect(() => {
    if (!current) return
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(timer)
  }, [current])

  const runs = endurance?.runs ?? []

  return (
    <Panel title="Endurance">
      {current ? (
        <>
          <div className="teleop-stats">
            <Stat label="motion" value={current.motion} />
            <Stat label="cycles" value={String(current.cycles)} />
            {current.carried_cycles > 0 && (
              <Stat
                label="carried over"
                value={
                  current.carried_estimated > 0
                    ? `${current.carried_cycles} (${current.carried_estimated} estimated)`
                    : `${current.carried_cycles} from ${current.continues ?? 'an earlier run'}`
                }
                title={current.carried_note ?? undefined}
              />
            )}
            <Stat label="elapsed" value={duration(endOf(current, now) - current.started_at)} />
            <Stat label="cycles / h" value={perHour(current, now)} />
            <Stat
              label="faults"
              value={`${current.bus_errors} bus · ${current.latched_motors} latched`}
            />
          </div>
          <table className="traj-table endurance-fingers">
            <thead>
              <tr>
                <th>finger</th>
                <th>peak last cycle</th>
                <th>tactile</th>
                <th>drops</th>
                <th>last drop</th>
                <th>drops / h</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(current.drops ?? current.fingers).map((finger) => {
                const f = current.fingers[finger]
                return (
                  <tr key={finger}>
                    <td className="traj-name">{finger}</td>
                    <td>{f?.peak_n == null ? '—' : `${f.peak_n.toFixed(2)} N`}</td>
                    <td
                      className={
                        f?.health === 'ok'
                          ? 'endurance-ok'
                          : f?.health
                            ? 'endurance-bad'
                            : undefined
                      }
                    >
                      {f ? (f.health ?? 'no sensor') : '—'}
                    </td>
                    <td
                      className={current.drops?.[finger]?.count ? 'endurance-bad' : undefined}
                      title={dropStats(current.drops?.[finger])}
                    >
                      {current.drops?.[finger]?.count ?? '—'}
                    </td>
                    <td>{lastDrop(current, finger, now)}</td>
                    <td>{dropsPerHour(current, finger, now)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      ) : (
        <div className="panel-hint">
          loop a trajectory to start an endurance run: every cycle is counted and kept in the hand's
          folder
        </div>
      )}
      {runs.length > 0 && (
        <table className="traj-table endurance-runs">
          <thead>
            <tr>
              <th>started</th>
              <th>motion</th>
              <th>result</th>
              <th>ran</th>
              <th>cycles / h</th>
              <th>faults</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>{started(run)}</td>
                <td className="traj-name">{run.motion}</td>
                <td>{outcome(run)}</td>
                <td>{duration(endOf(run, now) - run.started_at)}</td>
                <td>{perHour(run, now)}</td>
                <td>{run.bus_errors + run.latched_motors}</td>
                <td>
                  <a
                    className="btn btn-secondary"
                    href={`/api/endurance/${encodeURIComponent(run.run_id)}.csv`}
                    download
                  >
                    csv
                  </a>
                  {run.drops && (
                    <a
                      className="btn btn-secondary"
                      href={`/api/endurance/${encodeURIComponent(run.run_id)}-drops.csv`}
                      download
                    >
                      drops
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

function Stat({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="teleop-stat-row" title={title}>
      <span className="teleop-stat-label">{label}</span>
      <span className="teleop-stat-value">{value}</span>
    </div>
  )
}

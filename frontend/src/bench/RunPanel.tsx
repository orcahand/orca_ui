// What the run is doing and what it has measured: per motor its own cycle
// count, rate and state, the settled reach and holding current, and a strip
// chart of position and current for all of them.

import type { MotorCycleExtra, MotorCycleMotorReport, MotorCycleResult } from '../api/types'
import { useOperationStore } from '../state/operationStore'
import { useBenchStore } from './benchStore'
import { BenchChart } from './BenchChart'
import { formatDeg, formatDuration, formatMa } from './useMotorLive'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bench-stat" title={hint}>
      <span className="bench-stat-value">{value}</span>
      <span className="bench-stat-label">{label}</span>
    </div>
  )
}

function shortfallClass(row: MotorCycleMotorReport): string {
  if (row.shortfall_deg === null) return ''
  if (row.shortfall_deg > 10) return 'err'
  if (row.shortfall_deg > 3) return 'warn'
  return 'ok'
}

const STATE_LABEL: Record<MotorCycleMotorReport['state'], string> = {
  approach: 'to start',
  moving: 'moving',
  settling: 'arriving',
  holding: 'holding',
  done: 'done',
}

function stateText(row: MotorCycleMotorReport, running: boolean): string {
  if (!running) return row.state === 'done' ? 'done' : 'stopped'
  const end = row.heading === 'to' ? 'B' : 'A'
  if (row.state === 'done') return 'done'
  if (row.state === 'approach') return `→ ${end}`
  return `${STATE_LABEL[row.state]} → ${end}`
}

export function RunPanel() {
  const operation = useOperationStore((s) => s.operation)
  const motors = useBenchStore((s) => s.motors)
  const numberOf = (id: number) => motors.find((m) => m.id === id)?.number ?? null
  const ours = operation?.kind === 'motor_cycle' ? operation : null
  const extra = (ours?.extra ?? null) as MotorCycleExtra | null
  const result = (ours?.result ?? null) as MotorCycleResult | null
  const running = ours !== null && ours.state !== 'done' && ours.state !== 'error'
  // A stopped run has no result; its last published extra carries the log.
  const logRows = result?.log_rows ?? extra?.log?.rows ?? 0
  const logFiles = result?.log_files ?? extra?.log?.files ?? []
  const logFile = logFiles.length > 0 ? logFiles[logFiles.length - 1] : null

  const progress = extra?.progress ?? ours?.progress ?? null
  const headline = !ours
    ? 'no run yet'
    : ours.state === 'error'
      ? `stopped: ${ours.error ?? 'error'}`
      : ours.state === 'done'
        ? `finished — ${ours.detail ?? ''}`
        : ours.state === 'paused'
          ? 'paused'
          : (ours.detail ?? ours.phase ?? 'running')

  const slowest = extra?.motors.reduce<number | null>(
    (acc, m) => (m.eta_s === null ? acc : Math.max(acc ?? 0, m.eta_s)),
    null,
  )
  const anyLoop = extra?.motors.some((m) => m.loop) ?? false

  return (
    <section className="panel bench-run">
      <div className="panel-header">
        <h2>Progress</h2>
        <span className={`panel-hint bench-run-state ${ours?.state ?? ''}`}>{headline}</span>
      </div>

      <div className="bench-progress" aria-hidden={progress === null}>
        <div
          className={`bench-progress-fill ${running ? 'live' : ''}`}
          style={{ width: `${Math.round((progress ?? 0) * 100)}%` }}
        />
      </div>

      <div className="bench-stats">
        <Stat label="elapsed" value={formatDuration(extra?.elapsed_s)} />
        <Stat
          label="finished"
          value={extra ? `${extra.finished} / ${extra.total}` : '—'}
          hint="motors that completed their count"
        />
        <Stat
          label="remaining"
          value={anyLoop ? '∞' : formatDuration(slowest)}
          hint="until the slowest motor finishes"
        />
        {logFile && (
          <div
            className={`bench-stat bench-log-file ${running && extra?.log?.on ? 'live' : ''}`}
            title={`${logRows.toLocaleString()} rows in ${logFiles.length} file${logFiles.length === 1 ? '' : 's'} — in the model's logs/ folder`}
          >
            <a
              className="bench-stat-value"
              href={`/api/bench/logs/${encodeURIComponent(logFile)}`}
              download={logFile}
            >
              ⬇ CSV
            </a>
            <span className="bench-stat-label">
              {logFiles.length > 1 ? (
                <>
                  {logFile.replace(/-\d+\.csv$/, '')} ·{' '}
                  {logFiles.map((name, i) => (
                    <a
                      key={name}
                      href={`/api/bench/logs/${encodeURIComponent(name)}`}
                      download={name}
                      title={name}
                    >
                      {i + 1}
                    </a>
                  ))}
                </>
              ) : (
                logFile
              )}
            </span>
          </div>
        )}
      </div>

      <div className="bench-table-scroll">
      <table className="bench-table">
        <thead>
          <tr>
            <th>motor</th>
            <th>cycles</th>
            <th title="cycles per minute, averaged over the last 10">rate</th>
            <th>state</th>
            <th title="settled position at A / B">reached A ↔ B</th>
            <th title="commanded travel minus achieved travel — grows as a cable stretches">
              shortfall
            </th>
            <th title="mean current while holding at A / B — falls as a tendon slackens">
              hold A / B
            </th>
            <th title="highest current seen during the run">peak</th>
            <th title="shaft turns commanded so far">odometer</th>
            <th title="now / max during run">temp</th>
          </tr>
        </thead>
        <tbody>
          {(extra?.motors ?? []).map((row) => (
            <tr key={row.id} className={row.state === 'done' ? 'done' : ''}>
              <td>
                {numberOf(row.id) ?? row.id}
                <small> id {row.id}</small>
              </td>
              <td>
                {row.cycle}
                {row.loop ? <small> ∞</small> : <small> / {row.cycles}</small>}
              </td>
              <td>{row.cycles_per_min ? `${row.cycles_per_min.toFixed(1)}/min` : '—'}</td>
              <td>{stateText(row, running)}</td>
              <td>
                {formatDeg(row.reached_from_deg)} ↔ {formatDeg(row.reached_to_deg)}
                {row.span_deg !== null && <small> ({row.span_deg.toFixed(1)}°)</small>}
              </td>
              <td className={shortfallClass(row)}>
                {row.shortfall_deg === null ? '—' : `${row.shortfall_deg.toFixed(1)}°`}
              </td>
              <td>
                {formatMa(row.hold_current_from_ma)} / {formatMa(row.hold_current_to_ma)}
              </td>
              <td>{formatMa(row.peak_current_ma)}</td>
              <td>{(row.travel_deg / 360).toFixed(1)} turns</td>
              <td>
                {row.temp_c === null ? '—' : `${row.temp_c.toFixed(0)}`}
                {row.temp_max_c !== null && <small> / {row.temp_max_c.toFixed(0)} °C</small>}
              </td>
            </tr>
          ))}
          {!extra && (
            <tr>
              <td colSpan={10} className="bench-empty">
                Hold the motors, set A and B on each, then Start.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>

      <BenchChart />
    </section>
  )
}

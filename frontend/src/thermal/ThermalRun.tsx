// What the run is doing and what it has measured: phase and time left, the
// hottest motor, per motor its temperature from start to now, the rate it
// is climbing, the current it actually drew and whether it was cut — and
// the temperature chart of the whole run.

import { useEffect } from 'react'
import type { ThermalExtra, ThermalMotorReport, ThermalResult } from '../api/types'
import { useBenchStore } from '../bench/benchStore'
import { formatDuration, formatMa } from '../bench/useMotorLive'
import { useOperationStore } from '../state/operationStore'
import { ThermalChart } from './ThermalChart'
import { trackThermalOperation } from './thermalHistory'

function Stat({ label, value, hint, className }: { label: string; value: string; hint?: string; className?: string }) {
  return (
    <div className={`bench-stat ${className ?? ''}`} title={hint}>
      <span className="bench-stat-value">{value}</span>
      <span className="bench-stat-label">{label}</span>
    </div>
  )
}

const STATE_LABEL: Record<ThermalMotorReport['state'], string> = {
  driving: 'driving',
  cooling: 'cooling',
  limit: 'cut: limit',
  slipped: 'cut: slipped',
  done: 'done',
}

function stateClass(row: ThermalMotorReport): string {
  if (row.state === 'slipped') return 'err'
  if (row.state === 'limit') return 'warn'
  return ''
}

function temp(v: number | null, digits = 0): string {
  return v === null ? '—' : v.toFixed(digits)
}

export function ThermalRun() {
  const operation = useOperationStore((s) => s.operation)
  const motors = useBenchStore((s) => s.motors)
  const numberOf = (id: number) => motors.find((m) => m.id === id)?.number ?? null
  const ours = operation?.kind === 'motor_thermal' ? operation : null
  const extra = (ours?.extra ?? null) as ThermalExtra | null
  const result = (ours?.result ?? null) as ThermalResult | null
  const running = ours !== null && ours.state !== 'done' && ours.state !== 'error'

  useEffect(() => {
    trackThermalOperation(operation)
  }, [operation])

  const logRows = result?.log_rows ?? extra?.log?.rows ?? 0
  const logFiles = result?.log_files ?? extra?.log?.files ?? []
  const logFile = logFiles.length > 0 ? logFiles[logFiles.length - 1] : null
  const progress = extra?.progress ?? ours?.progress ?? null
  const rows = extra?.motors ?? result?.motors ?? []
  const hottest = rows.reduce<ThermalMotorReport | null>(
    (acc, m) => (m.temp_c === null ? acc : acc === null || m.temp_c > (acc.temp_c ?? -1) ? m : acc),
    null,
  )
  const remaining =
    extra && extra.phase_total_s !== null ? Math.max(0, extra.phase_total_s - extra.phase_elapsed_s) : null

  const headline = !ours
    ? 'no run yet'
    : ours.state === 'error'
      ? `stopped: ${ours.error ?? 'error'}`
      : ours.state === 'done'
        ? `finished — ${ours.detail ?? ''}`
        : ours.state === 'paused'
          ? 'paused'
          : (ours.detail ?? ours.phase ?? 'running')

  return (
    <section className="panel bench-run thermal-run">
      <div className="panel-header">
        <h2>Run</h2>
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
          label={extra ? `${extra.phase} left` : 'phase'}
          value={extra ? (extra.phase_total_s === null ? '∞' : formatDuration(remaining)) : '—'}
          hint="time left in the current phase"
        />
        <Stat
          label="driving"
          value={extra ? `${extra.driving} / ${extra.motors.length}` : '—'}
          hint="motors still being driven"
        />
        <Stat
          label="hottest"
          value={hottest ? `M${numberOf(hottest.id) ?? hottest.id} ${temp(hottest.temp_c)} °C` : '—'}
          hint={extra ? `cut at ${extra.temp_limit_c} °C` : undefined}
          className={
            hottest && extra && hottest.temp_c !== null
              ? hottest.temp_c >= extra.temp_limit_c
                ? 'err'
                : hottest.temp_c >= extra.temp_limit_c - 10
                  ? 'warn'
                  : ''
              : ''
          }
        />
        {logFile && (
          <div
            className={`bench-stat bench-log-file ${running && extra?.log?.on ? 'live' : ''}`}
            title={`${logRows.toLocaleString()} rows in ${logFiles.length} file${logFiles.length === 1 ? '' : 's'} — in the model's logs/ folder`}
          >
            <a className="bench-stat-value" href={`/api/bench/logs/${encodeURIComponent(logFile)}`} download={logFile}>
              ⬇ CSV
            </a>
            <span className="bench-stat-label">
              {logFiles.length > 1 ? (
                <>
                  {logFile.replace(/-\d+\.csv$/, '')} ·{' '}
                  {logFiles.map((name, i) => (
                    <a key={name} href={`/api/bench/logs/${encodeURIComponent(name)}`} download={name} title={name}>
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
              <th>state</th>
              <th title="temperature at start → now (max during the run)">temp start → now</th>
              <th title="now minus start">rise</th>
              <th title="slope over the last minute">rate</th>
              <th title="goal current now / what the motor reports drawing">goal / actual</th>
              <th title="RMS of the drawn current while driving">rms</th>
              <th title="shaft movement since start (max)">{extra?.load === 'free' ? 'moved' : 'drift'}</th>
              <th title="when the motor was cut or the heating ended">stopped</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.state === 'done' ? 'done' : ''}>
                <td>
                  M{numberOf(row.id) ?? row.id}
                  <small> id {row.id}</small>
                  {row.partner !== null && <small> ↔ M{numberOf(row.partner) ?? row.partner}</small>}
                  {row.invert && <small title="current inverted"> −</small>}
                  {row.phase_s > 0 && <small title="phase offset"> +{Math.round(row.phase_s * 1000)} ms</small>}
                </td>
                <td className={stateClass(row)}>
                  {running ? STATE_LABEL[row.state] : row.state === 'done' ? 'done' : row.state}
                  {row.via_partner && <small> (partner)</small>}
                </td>
                <td>
                  {temp(row.temp_start_c)} → <b>{temp(row.temp_c)}</b>
                  {row.temp_max_c !== null && <small> ({temp(row.temp_max_c)}) °C</small>}
                </td>
                <td className={row.rise_c !== null && row.rise_c > 0 ? 'warn' : ''}>
                  {row.rise_c === null ? '—' : `${row.rise_c >= 0 ? '+' : ''}${row.rise_c.toFixed(1)} °C`}
                </td>
                <td>{row.rate_c_per_min === null ? '—' : `${row.rate_c_per_min >= 0 ? '+' : ''}${row.rate_c_per_min.toFixed(2)} °C/min`}</td>
                <td>
                  {formatMa(row.goal_ma)} / {formatMa(row.current_ma)}
                </td>
                <td>{formatMa(row.current_rms_ma)}</td>
                <td className={extra?.load === 'free' ? '' : row.drift_max_deg > 10 ? 'err' : row.drift_max_deg > 3 ? 'warn' : ''}>
                  {row.drift_deg === null ? '—' : `${row.drift_deg.toFixed(1)}°`}
                  <small> (max {row.drift_max_deg.toFixed(1)}°)</small>
                </td>
                <td>{row.stopped_s === null ? '—' : formatDuration(row.stopped_s)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="bench-empty">
                  Hold the motors, set the waveform, then Start.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <ThermalChart />
    </section>
  )
}

// What a step's check reported: its summary, metrics and graphs. Compare steps
// read as two columns, main | branch, with the difference and a highlight on
// every metric the check did not accept.

import type { HwCheckResult, HwMetric, HwSession, HwSideName } from '../../api/hardwareTests'
import { difference, formatValue } from './hwFormat'
import { SeriesCharts } from './SeriesChart'
import { StatusChip } from './hwShared'

function okClass(metric: HwMetric): string {
  return metric.ok === false ? 'hwt-metric-bad' : metric.ok === true ? 'hwt-metric-ok' : ''
}

function okMark(metric: HwMetric): string {
  return metric.ok === false ? '✗' : metric.ok === true ? '✓' : ''
}

function SideHeader({ name, session }: { name: HwSideName; session: HwSession }) {
  const side = session.sides[name]
  return (
    <div className={`hwt-side hwt-side-${name}${side?.available ? '' : ' hwt-side-off'}`}>
      <div className="hwt-side-name">{name}</div>
      <div className="hwt-side-version">{side?.version ?? 'version unknown'}</div>
      {side && !side.available && <div className="hwt-hint warn">{side.reason}</div>}
    </div>
  )
}

function CompareMetrics({ metrics }: { metrics: HwMetric[] }) {
  return (
    <table className="hwt-metrics">
      <thead>
        <tr>
          <th>METRIC</th>
          <th className="hwt-col-main">MAIN</th>
          <th className="hwt-col-branch">BRANCH</th>
          <th>DIFFERENCE</th>
          <th>UNIT</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric, i) => (
          <tr key={`${metric.name}-${i}`} className={okClass(metric)}>
            <td>{metric.name}</td>
            <td className="hwt-col-main">{formatValue(metric.main)}</td>
            <td className="hwt-col-branch">{formatValue(metric.value)}</td>
            <td>{difference(metric.value, metric.main)}</td>
            <td className="hwt-dim">{metric.unit}</td>
            <td>{okMark(metric)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function PlainMetrics({ metrics }: { metrics: HwMetric[] }) {
  return (
    <table className="hwt-metrics">
      <thead>
        <tr>
          <th>METRIC</th>
          <th>VALUE</th>
          <th>UNIT</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric, i) => (
          <tr key={`${metric.name}-${i}`} className={okClass(metric)}>
            <td>{metric.name}</td>
            <td>{formatValue(metric.value)}</td>
            <td className="hwt-dim">{metric.unit}</td>
            <td>{okMark(metric)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function CheckResultView({
  check,
  compare,
  session,
}: {
  check: HwCheckResult
  compare: boolean
  session: HwSession
}) {
  const sided =
    compare ||
    check.metrics.some((m) => m.main !== null && m.main !== undefined) ||
    check.series.some((s) => s.side !== 'console')
  const failing = check.metrics.filter((m) => m.ok === false).length
  const details = check.details && Object.keys(check.details).length > 0 ? check.details : null

  return (
    <div className="hwt-check">
      <div className="hwt-check-head">
        <StatusChip status={check.status} />
        <span className="hwt-check-summary">{check.summary}</span>
      </div>
      {failing > 0 && (
        <div className="hwt-hint err">
          {failing} metric{failing === 1 ? '' : 's'} outside the pass rule
        </div>
      )}
      {sided && (
        <div className="hwt-sides">
          <SideHeader name="main" session={session} />
          <SideHeader name="branch" session={session} />
        </div>
      )}
      {check.metrics.length > 0 &&
        (sided ? (
          <CompareMetrics metrics={check.metrics} />
        ) : (
          <PlainMetrics metrics={check.metrics} />
        ))}
      <SeriesCharts series={check.series} />
      {details && (
        <details className="hwt-details">
          <summary>details</summary>
          <pre>{JSON.stringify(details, null, 2)}</pre>
        </details>
      )}
    </div>
  )
}

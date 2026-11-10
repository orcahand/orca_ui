// One uPlot chart overlaying a check's series that share a name, one line per
// side (main | branch | console), on a common x axis.

import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { HwSeries } from '../../api/hardwareTests'
import { usePalette } from '../../theme/themeStore'

const HEIGHT = 180

function sortedTable(series: HwSeries): [number[], number[]] {
  const pairs = series.x
    .map((x, i) => [x, series.y[i]] as const)
    .filter(([x, y]) => Number.isFinite(x) && y !== undefined)
    .sort((a, b) => a[0] - b[0])
  return [pairs.map(([x]) => x), pairs.map(([, y]) => y)]
}

export function SeriesChart({ title, series }: { title: string; series: HwSeries[] }) {
  const palette = usePalette()
  const hostRef = useRef<HTMLDivElement>(null)
  const seriesRef = useRef(series)
  seriesRef.current = series
  // The session is re-polled every second; rebuild the plot only when the data changes.
  const signature = series
    .map((s) => `${s.side}|${s.name}|${s.x.length}|${s.x[s.x.length - 1]}|${s.y[s.y.length - 1]}`)
    .join(';')

  useEffect(() => {
    const series = seriesRef.current
    const host = hostRef.current
    if (!host || series.length === 0) return
    const sideColor: Record<string, string> = {
      main: palette.purple,
      branch: palette.accent,
      console: palette.ok,
    }
    const data = uPlot.join(series.map(sortedTable))
    const axis = {
      stroke: palette.chart.axis,
      grid: { stroke: palette.chart.grid, width: 1 },
      ticks: { stroke: palette.chart.ticks },
      font: `9px 'Space Mono'`,
      labelFont: `9px 'Space Mono'`,
    }
    const plot = new uPlot(
      {
        width: host.clientWidth || 480,
        height: HEIGHT,
        padding: [6, 8, 0, 0],
        cursor: { show: true, y: false },
        legend: { show: true, live: true },
        scales: { x: { time: false } },
        axes: [
          { ...axis, label: series[0].x_label || undefined, size: 30, labelSize: 14 },
          { ...axis, label: series[0].y_label || undefined, size: 44, labelSize: 14 },
        ],
        series: [
          { label: series[0].x_label || 'x' },
          ...series.map((s, i) => ({
            label: series.length > 1 && s.side === 'console' ? `${s.name} ${i + 1}` : s.side,
            stroke: sideColor[s.side] ?? palette.muted,
            width: 1.5,
            spanGaps: true,
            points: { show: false },
          })),
        ],
      },
      data,
      host,
    )
    const observer = new ResizeObserver(() => {
      if (host.clientWidth > 0) plot.setSize({ width: host.clientWidth, height: HEIGHT })
    })
    observer.observe(host)
    return () => {
      observer.disconnect()
      plot.destroy()
    }
  }, [signature, palette])

  return (
    <div className="hwt-chart">
      <div className="hwt-chart-title">{title}</div>
      <div ref={hostRef} />
    </div>
  )
}

// Groups series by name so each chart overlays the sides of one quantity.
export function SeriesCharts({ series }: { series: HwSeries[] }) {
  if (series.length === 0) return null
  const groups = new Map<string, HwSeries[]>()
  for (const s of series) {
    if (!groups.has(s.name)) groups.set(s.name, [])
    groups.get(s.name)!.push(s)
  }
  return (
    <div className="hwt-charts">
      {[...groups.entries()].map(([name, group]) => (
        <SeriesChart key={name} title={name} series={group} />
      ))}
    </div>
  )
}

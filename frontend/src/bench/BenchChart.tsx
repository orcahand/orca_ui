// Strip charts of shaft position and current for every motor, last 30 s,
// fed from the bench history rings; MotorStripChart is one of them on its
// own, for the fingers monitor. Rebuilt on a theme or motor-set change
// (uPlot bakes colours in at construction); the rings outlive the plot.

import { useEffect, useMemo, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { usePalette } from '../theme/themeStore'
import { useBenchStore } from './benchStore'
import { benchHistory, HISTORY_S } from './useMotorLive'

const REDRAW_MS = 100

function buildPlot(
  host: HTMLDivElement,
  ids: string[],
  colors: string[],
  unit: string,
  chart: { axis: string; grid: string; ticks: string },
  height = 110,
): uPlot {
  return new uPlot(
    {
      width: host.clientWidth || 480,
      height,
      padding: [6, 8, 0, 0],
      cursor: { show: true, x: true, y: false },
      legend: { show: false },
      scales: { x: { time: false, range: [-HISTORY_S, 0] } },
      axes: [
        {
          stroke: chart.axis,
          grid: { stroke: chart.grid, width: 1 },
          ticks: { stroke: chart.ticks },
          font: `9px 'Space Mono'`,
          size: 22,
          values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}s`),
        },
        {
          stroke: chart.axis,
          grid: { stroke: chart.grid, width: 1 },
          ticks: { stroke: chart.ticks },
          font: `9px 'Space Mono'`,
          size: 48,
          values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}${unit}`),
        },
      ],
      series: [
        {},
        ...ids.map((id, i) => ({
          label: id,
          stroke: colors[i % colors.length],
          width: 1.25,
          points: { show: false },
          spanGaps: false,
        })),
      ],
    },
    [[], ...ids.map(() => [])],
    host,
  )
}

/** Evenly spread hues for however many motors are on the bus; the first
 *  few are the palette's own so small benches look as they always did. */
export function seriesColors(palette: ReturnType<typeof usePalette>, count: number): string[] {
  const base = [palette.accent, palette.purple, palette.ok, palette.warn, palette.err]
  return Array.from({ length: count }, (_, i) =>
    i < base.length ? base[i] : `hsl(${Math.round((i * 137.508) % 360)} 60% 58%)`,
  )
}

/** One strip chart of a motor quantity, last 30 s, for the ids given. */
export function MotorStripChart({
  source,
  ids,
  unit,
  height = 110,
}: {
  source: 'positions' | 'currents'
  ids: string[]
  unit: string
  height?: number
}) {
  const palette = usePalette()
  const host = useRef<HTMLDivElement>(null)
  const key = ids.join(',')
  useEffect(() => {
    if (!host.current || ids.length === 0) return
    const plot = buildPlot(host.current, ids, seriesColors(palette, ids.length), unit, palette.chart, height)
    const interval = window.setInterval(() => feed([plot], [benchHistory[source]], ids), REDRAW_MS)
    const resize = () => host.current && plot.setSize({ width: host.current.clientWidth, height })
    window.addEventListener('resize', resize)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('resize', resize)
      plot.destroy()
    }
    // `key` stands in for the ids array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, palette, source, unit, height])
  return <div ref={host} />
}

function feed(plots: uPlot[], sources: Map<string, { snapshot(): Float64Array }>[], ids: string[]): void {
  const time = benchHistory.time.snapshot()
  if (time.length < 2) return
  const nowS = Date.now() / 1000
  // Anchor to the wall clock, not the newest sample, so the trace scrolls
  // instead of shimmering with sample jitter.
  let first = 0
  while (first < time.length && time[first] - nowS < -HISTORY_S) first += 1
  const xs: number[] = []
  for (let i = first; i < time.length; i++) xs.push(time[i] - nowS)
  plots.forEach((plot, p) => {
    const data: (number | null)[][] = [xs]
    for (const id of ids) {
      const ring = sources[p].get(id)
      const values = ring ? ring.snapshot() : new Float64Array(0)
      // Rings are pushed in lockstep with time; a motor that joined late
      // is shorter at the front.
      const offset = values.length - time.length
      const column: (number | null)[] = []
      for (let i = first; i < time.length; i++) {
        const v = values[i + offset]
        column.push(v === undefined || Number.isNaN(v) ? null : v)
      }
      data.push(column)
    }
    plot.setData(data as uPlot.AlignedData)
  })
}

export function BenchChart() {
  const palette = usePalette()
  const motors = useBenchStore((s) => s.motors)
  const ids = useMemo(() => motors.map((m) => String(m.id)), [motors])
  const posHost = useRef<HTMLDivElement>(null)
  const curHost = useRef<HTMLDivElement>(null)
  const key = ids.join(',')

  useEffect(() => {
    const hosts = [posHost.current, curHost.current]
    if (!hosts[0] || !hosts[1] || ids.length === 0) return
    const colors = seriesColors(palette, ids.length)
    const plots = [
      buildPlot(hosts[0], ids, colors, '°', palette.chart),
      buildPlot(hosts[1], ids, colors, 'mA', palette.chart),
    ]
    const sources = [benchHistory.positions, benchHistory.currents]

    const interval = window.setInterval(() => feed(plots, sources, ids), REDRAW_MS)
    const resize = () => {
      plots.forEach((plot, i) => {
        const host = hosts[i]
        if (host) plot.setSize({ width: host.clientWidth, height: 110 })
      })
    }
    window.addEventListener('resize', resize)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('resize', resize)
      plots.forEach((plot) => plot.destroy())
    }
    // `key` stands in for the ids array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, palette])

  if (ids.length === 0) return null
  const colors = seriesColors(palette, ids.length)
  return (
    <div className="bench-charts">
      <div className="bench-chart-legend">
        {motors.map((motor, i) => (
          <span key={motor.id} style={{ color: colors[i % colors.length] }}>
            ● motor {motor.number}
          </span>
        ))}
      </div>
      <div className="bench-chart-title">position</div>
      <div ref={posHost} />
      <div className="bench-chart-title">current</div>
      <div ref={curHost} />
    </div>
  )
}

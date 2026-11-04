// Temperature of every motor over the whole run (minutes on the x axis, the
// cut limit as a dashed line), and the last 30 s of current from the live
// stream underneath so the waveform can be seen doing what was asked.

import { useEffect, useMemo, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { useBenchStore } from '../bench/benchStore'
import { benchHistory, HISTORY_S, useMotorLive } from '../bench/useMotorLive'
import { usePalette, useThemeStore } from '../theme/themeStore'
import { onTracesChange, thermalTraces } from './thermalHistory'
import { traceColor } from './thermalStore'

const REDRAW_MS = 250

function axes(chart: { axis: string; grid: string; ticks: string }, xFmt: (v: number) => string, yFmt: (v: number) => string) {
  return [
    {
      stroke: chart.axis,
      grid: { stroke: chart.grid, width: 1 },
      ticks: { stroke: chart.ticks },
      font: `9px 'Space Mono'`,
      size: 22,
      values: (_u: uPlot, ticks: number[]) => ticks.map(xFmt),
    },
    {
      stroke: chart.axis,
      grid: { stroke: chart.grid, width: 1 },
      ticks: { stroke: chart.ticks },
      font: `9px 'Space Mono'`,
      size: 48,
      values: (_u: uPlot, ticks: number[]) => ticks.map(yFmt),
    },
  ]
}

export function ThermalChart() {
  const palette = usePalette()
  const dark = useThemeStore((s) => s.theme) === 'dark'
  const motors = useBenchStore((s) => s.motors)
  const ids = useMemo(() => motors.map((m) => String(m.id)), [motors])
  const key = ids.join(',')
  const tempHost = useRef<HTMLDivElement>(null)
  const curHost = useRef<HTMLDivElement>(null)
  const colors = useMemo(() => ids.map((_, i) => traceColor(i, ids.length, dark)), [ids, dark])

  // Install the live recorder so the current strip has data.
  useMotorLive(() => undefined)

  useEffect(() => {
    const hostT = tempHost.current
    const hostC = curHost.current
    if (!hostT || !hostC || ids.length === 0) return
    const series = (unit: string) =>
      ids.map((id, i) => ({
        label: `${unit}${id}`,
        stroke: colors[i],
        width: 1.25,
        points: { show: false },
        spanGaps: true,
      }))
    const tempPlot = new uPlot(
      {
        width: hostT.clientWidth || 480,
        height: 220,
        padding: [6, 8, 0, 0],
        cursor: { show: true, x: true, y: false },
        legend: { show: false },
        scales: { x: { time: false } },
        axes: axes(
          palette.chart,
          (v) => (v >= 60 ? `${(v / 60).toFixed(v % 60 === 0 ? 0 : 1)}m` : `${v.toFixed(0)}s`),
          (v) => `${v.toFixed(0)}°`,
        ),
        series: [
          {},
          ...series(''),
          { label: 'limit', stroke: palette.err, width: 1, dash: [4, 4], points: { show: false } },
        ],
      },
      [[], ...ids.map(() => []), []],
      hostT,
    )
    const curPlot = new uPlot(
      {
        width: hostC.clientWidth || 480,
        height: 110,
        padding: [6, 8, 0, 0],
        cursor: { show: true, x: true, y: false },
        legend: { show: false },
        scales: { x: { time: false, range: [-HISTORY_S, 0] } },
        axes: axes(palette.chart, (v) => `${v.toFixed(0)}s`, (v) => `${v.toFixed(0)}mA`),
        series: [{}, ...series('')],
      },
      [[], ...ids.map(() => [])],
      hostC,
    )

    const redrawTemps = () => {
      const t = thermalTraces.t
      if (t.length < 1) {
        tempPlot.setData([[], ...ids.map(() => []), []] as uPlot.AlignedData)
        return
      }
      const data: (number | null)[][] = [t]
      for (const id of ids) {
        const s = thermalTraces.temps.get(id)
        data.push(s ? (s.length === t.length ? s : t.map((_, i) => s[i] ?? null)) : t.map(() => null))
      }
      data.push(t.map(() => thermalTraces.limitC))
      tempPlot.setData(data as uPlot.AlignedData)
    }
    const redrawCurrents = () => {
      const time = benchHistory.time.snapshot()
      if (time.length < 2) return
      const nowS = Date.now() / 1000
      let first = 0
      while (first < time.length && time[first] - nowS < -HISTORY_S) first += 1
      const xs: number[] = []
      for (let i = first; i < time.length; i++) xs.push(time[i] - nowS)
      const data: (number | null)[][] = [xs]
      for (const id of ids) {
        const ring = benchHistory.currents.get(id)
        const values = ring ? ring.snapshot() : new Float64Array(0)
        const offset = values.length - time.length
        const column: (number | null)[] = []
        for (let i = first; i < time.length; i++) {
          const v = values[i + offset]
          column.push(v === undefined || Number.isNaN(v) ? null : v)
        }
        data.push(column)
      }
      curPlot.setData(data as uPlot.AlignedData)
    }
    redrawTemps()
    const unsubscribe = onTracesChange(redrawTemps)
    const interval = window.setInterval(redrawCurrents, REDRAW_MS)
    const resize = () => {
      tempPlot.setSize({ width: hostT.clientWidth, height: 220 })
      curPlot.setSize({ width: hostC.clientWidth, height: 110 })
    }
    window.addEventListener('resize', resize)
    return () => {
      unsubscribe()
      window.clearInterval(interval)
      window.removeEventListener('resize', resize)
      tempPlot.destroy()
      curPlot.destroy()
    }
    // `key` stands in for the ids array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, palette, dark])

  if (ids.length === 0) return null
  return (
    <div className="bench-charts thermal-charts">
      <div className="bench-chart-legend thermal-legend">
        {motors.map((motor, i) => (
          <span key={motor.id} style={{ color: colors[i] }}>
            ● M{motor.number}
          </span>
        ))}
        <span style={{ color: palette.err }}>┄ limit</span>
      </div>
      <div className="bench-chart-title">temperature over the run</div>
      <div ref={tempHost} />
      <div className="bench-chart-title">current, last 30 s</div>
      <div ref={curHost} />
    </div>
  )
}

// Per-joint strip chart (uPlot): last 8 s of measured (solid) + target
// (dashed). Mounted only while expanded, so collapsed sparklines cost nothing;
// history accumulates in the ring buffers regardless.

import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { jointHistory } from '../../state/streamStore'
import { usePalette } from '../../theme/themeStore'

const WINDOW_S = 8
const REDRAW_MS = 50

export function JointSparkline({ joint }: { joint: JointInfo }) {
  // uPlot bakes its colors into the config at construction, so the plot is
  // rebuilt on a theme change rather than repainted. Theme switches are a
  // deliberate, once-a-session act; the ring buffers outlive the plot, so the
  // trace comes straight back with its history intact.
  const { chart, accent, purple } = usePalette()
  const hostRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)
  const showTarget = useAppStore((s) => s.showSparklineTarget)

  useEffect(() => {
    plotRef.current?.setSeries(2, { show: showTarget })
  }, [showTarget])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const [romMin, romMax] = joint.rom
    const pad = (romMax - romMin) * 0.05
    const plot = new uPlot(
      {
        width: host.clientWidth || 420,
        height: 72,
        padding: [4, 8, 0, 0],
        cursor: { show: true, x: true, y: false },
        legend: { show: false },
        scales: {
          // x is seconds relative to "now" (negative past), fixed window so
          // the trace scrolls steadily instead of rescaling.
          x: { time: false, range: [-WINDOW_S, 0] },
          y: { range: [romMin - pad, romMax + pad] },
        },
        axes: [
          {
            stroke: chart.axis,
            grid: { stroke: chart.grid, width: 1 },
            ticks: { stroke: chart.ticks },
            font: `9px 'Space Mono'`,
            size: 24,
            values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}s`),
          },
          {
            stroke: chart.axis,
            grid: { stroke: chart.grid, width: 1 },
            ticks: { stroke: chart.ticks },
            font: `9px 'Space Mono'`,
            size: 36,
            values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}°`),
          },
        ],
        series: [
          {},
          { stroke: accent, width: 1.25, points: { show: false } },
          // Commanded target: off by default (EncoderPanel toggle), solid and
          // clearly distinct from the measured trace.
          {
            stroke: purple,
            width: 1.25,
            points: { show: false },
            show: useAppStore.getState().showSparklineTarget,
          },
        ],
      },
      [[], [], []],
      host,
    )
    plotRef.current = plot

    const measured = jointHistory.measured.get(joint.id)
    const target = jointHistory.target.get(joint.id)

    const interval = window.setInterval(() => {
      if (!measured || !target) return
      const time = jointHistory.time.snapshot()
      const m = measured.snapshot()
      const t = target.snapshot()
      const n = Math.min(time.length, m.length, t.length)
      if (n < 2) return
      // Anchor ages to the wall clock, not the newest sample: sample spacing
      // is slightly irregular, and re-pinning the curve to a jittery
      // reference made the whole trace shimmer between redraws.
      const nowS = Date.now() / 1000
      const offsetM = m.length - time.length
      const offsetT = t.length - time.length
      const xs: number[] = []
      const ms: number[] = []
      const ts: (number | null)[] = []
      for (let i = time.length - n; i < time.length; i++) {
        const age = time[i] - nowS // seconds, <= 0
        if (age < -WINDOW_S) continue
        xs.push(age)
        ms.push(m[i + offsetM])
        const targetValue = t[i + offsetT]
        ts.push(Number.isNaN(targetValue) ? null : targetValue)
      }
      plot.setData([xs, ms, ts])
    }, REDRAW_MS)

    return () => {
      window.clearInterval(interval)
      plotRef.current = null
      plot.destroy()
    }
  }, [joint, chart, accent, purple])

  return <div ref={hostRef} style={{ margin: '2px 0 6px 120px' }} />
}

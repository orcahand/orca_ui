// Per-joint strip chart (uPlot): last 8 s of measured (solid) + target
// (dashed). Mounted only while expanded, so collapsed sparklines cost nothing;
// history accumulates in the ring buffers regardless.

import { useEffect, useRef } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import type { JointInfo } from '../../api/types'
import { jointHistory } from '../../state/streamStore'
import { COLORS } from '../../theme/tokens'

const WINDOW_S = 8
const REDRAW_MS = 50

export function JointSparkline({ joint }: { joint: JointInfo }) {
  const hostRef = useRef<HTMLDivElement>(null)

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
            stroke: COLORS.dimmer,
            grid: { stroke: 'rgba(255,255,255,0.05)', width: 1 },
            ticks: { stroke: 'rgba(255,255,255,0.08)' },
            font: `9px 'Space Mono'`,
            size: 24,
            values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}s`),
          },
          {
            stroke: COLORS.dimmer,
            grid: { stroke: 'rgba(255,255,255,0.05)', width: 1 },
            ticks: { stroke: 'rgba(255,255,255,0.08)' },
            font: `9px 'Space Mono'`,
            size: 36,
            values: (_u, ticks) => ticks.map((v) => `${v.toFixed(0)}°`),
          },
        ],
        series: [
          {},
          { stroke: COLORS.accent, width: 1.25, points: { show: false } },
          { stroke: COLORS.dim, width: 1, dash: [4, 4], points: { show: false } },
        ],
      },
      [[], [], []],
      host,
    )

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
      plot.destroy()
    }
  }, [joint])

  return <div ref={hostRef} style={{ margin: '2px 0 6px 120px' }} />
}

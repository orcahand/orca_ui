// ROM-delta chart: for one calibration run, signed bars of measured − config
// per joint, diverging around 0°. Joints with an absolute sensor-measured
// ROM get one bar per hardstop (lower/upper); motor-only joints get a single
// grey travel bar (measured span − config span). The exact values are
// printed in the numeric strip under the axis — the chart shows the shape,
// the strip shows the numbers.

import { useMemo, useState } from 'react'
import type { CalibrationRun, JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useThemeStore } from '../../theme/themeStore'
import {
  extractRomRuns,
  fmtWhen,
  FOLD_COLOR,
  SERIES_DARK,
  SERIES_LIGHT,
} from './CalibrationRomChart'

const PLOT_H = 130
const MARGIN = { top: 8, right: 8, bottom: 64, left: 40 }
const COL_W = 44
const BAR_W = 7
// Matches the magnet table's drift threshold: a hardstop this far off
// config is flagged.
const WARN_DEG = 1.0
const STRIP_ROW_H = 12

function fmtDelta(delta: number): string {
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`
}

export function CalibrationDeltaChart({ runs }: { runs: CalibrationRun[] }) {
  const handInfo = useAppStore((s) => s.handInfo)
  const dark = useThemeStore((s) => s.theme) === 'dark'
  const romRuns = useMemo(() => {
    const configRom = new Map<string, [number, number]>(
      (handInfo?.joints ?? []).map((j) => [j.id, j.rom]),
    )
    return extractRomRuns(runs, dark, configRom)
  }, [runs, dark, handInfo])

  const [runKey, setRunKey] = useState<string | null>(null)
  const run = romRuns.find((r) => r.key === runKey) ?? romRuns[0]

  const joints: JointInfo[] = useMemo(() => {
    if (!handInfo || !run) return []
    return handInfo.joints.filter((j) => run.roms.has(j.id))
  }, [handInfo, run])

  // Per joint: lower/upper hardstop deltas (absolute sensor ROM), or the
  // travel delta alone when only the span was measured.
  const deltas = useMemo(() => {
    const map = new Map<
      string,
      { lo: number; hi: number; travel: null } | { travel: number }
    >()
    if (!run) return map
    for (const joint of joints) {
      const entry = run.roms.get(joint.id)
      if (!entry) continue
      if (entry.spanOnly) {
        map.set(joint.id, {
          travel: entry.deviation ??
            entry.rom[1] - entry.rom[0] - (joint.rom[1] - joint.rom[0]),
        })
      } else {
        map.set(joint.id, {
          lo: entry.rom[0] - joint.rom[0],
          hi: entry.rom[1] - joint.rom[1],
          travel: null,
        })
      }
    }
    return map
  }, [run, joints])

  if (!run || joints.length === 0) return null

  const [lowColor, highColor] = dark ? SERIES_DARK : SERIES_LIGHT

  const maxAbs = Math.max(
    2,
    ...[...deltas.values()].flatMap((d) =>
      'lo' in d ? [Math.abs(d.lo), Math.abs(d.hi)] : [Math.abs(d.travel)],
    ),
  )
  const yMax = maxAbs * 1.15
  const y = (delta: number) => MARGIN.top + ((yMax - delta) / (2 * yMax)) * PLOT_H
  const zeroY = y(0)
  const colX = (index: number) => MARGIN.left + index * COL_W + COL_W / 2

  const width = MARGIN.left + joints.length * COL_W + MARGIN.right
  const stripTop = MARGIN.top + PLOT_H + 46
  const height = stripTop + 2 * STRIP_ROW_H + 4
  const tickStep = maxAbs <= 3 ? 1 : maxAbs <= 8 ? 2 : maxAbs <= 20 ? 5 : 15
  const ticks: number[] = []
  for (let t = -Math.floor(yMax / tickStep) * tickStep; t <= yMax; t += tickStep)
    ticks.push(t)

  const bar = (
    jointIndex: number,
    delta: number,
    color: string,
    offset: number,
    label: string,
  ) => (
    <rect
      x={colX(jointIndex) + offset - BAR_W / 2}
      y={Math.min(zeroY, y(delta))}
      width={BAR_W}
      height={Math.max(1, Math.abs(y(delta) - zeroY))}
      rx={1.5}
      fill={color}
    >
      <title>{`${joints[jointIndex].id} ${label}: ${fmtDelta(delta)}°`}</title>
    </rect>
  )

  const stripCell = (
    jointIndex: number,
    row: number,
    delta: number,
    rowSpan = 1,
  ) => (
    <text
      x={colX(jointIndex)}
      y={stripTop + row * STRIP_ROW_H + (rowSpan * STRIP_ROW_H) / 2 + 3}
      textAnchor="middle"
      fontSize={8}
      style={{ fontVariantNumeric: 'tabular-nums' }}
      fill={Math.abs(delta) > WARN_DEG ? 'var(--warn)' : 'var(--dim)'}
    >
      {fmtDelta(delta)}
    </text>
  )

  return (
    <div style={{ margin: '12px 0 8px' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '2px 12px',
          alignItems: 'center',
          fontSize: 9,
          marginBottom: 4,
        }}
      >
        <span style={{ color: 'var(--dim)', fontWeight: 700 }}>
          Δ measured − config
        </span>
        <select
          value={run.key}
          onChange={(e) => setRunKey(e.target.value)}
          style={{
            fontSize: 9,
            fontFamily: 'var(--font)',
            background: 'var(--panel)',
            color: 'var(--text)',
            border: '1px solid var(--panel-border-strong)',
            borderRadius: 3,
            padding: '1px 4px',
          }}
        >
          {romRuns.map((r) => (
            <option key={r.key} value={r.key}>
              {fmtWhen(r.when)}
              {r.simulated ? ' (sim)' : ''}
            </option>
          ))}
        </select>
        <span style={{ color: 'var(--dimmer)' }}>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: lowColor,
              verticalAlign: -1,
              marginRight: 4,
            }}
          />
          lower hardstop
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: highColor,
              verticalAlign: -1,
              margin: '0 4px 0 12px',
            }}
          />
          upper hardstop
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: FOLD_COLOR,
              verticalAlign: -1,
              margin: '0 4px 0 12px',
            }}
          />
          travel only (no sensor anchor)
        </span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={width}
          height={height}
          style={{ display: 'block', fontFamily: 'var(--font)' }}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={width - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke={tick === 0 ? 'var(--dimmer)' : 'var(--panel-border)'}
                strokeWidth={1}
              />
              <text
                x={MARGIN.left - 5}
                y={y(tick) + 3}
                textAnchor="end"
                fontSize={8}
                fill="var(--dimmer)"
              >
                {tick > 0 ? `+${tick}` : tick}°
              </text>
            </g>
          ))}
          {joints.map((joint, jointIndex) => {
            const delta = deltas.get(joint.id)
            if (!delta) return null
            const entry = run.roms.get(joint.id)!
            return (
              <g key={joint.id}>
                {'lo' in delta ? (
                  <>
                    {bar(jointIndex, delta.lo, lowColor, -5,
                         `lower hardstop Δ (measured ${entry.rom[0].toFixed(1)}° vs config ${joint.rom[0].toFixed(1)}°)`)}
                    {bar(jointIndex, delta.hi, highColor, 5,
                         `upper hardstop Δ (measured ${entry.rom[1].toFixed(1)}° vs config ${joint.rom[1].toFixed(1)}°)`)}
                    {stripCell(jointIndex, 0, delta.lo)}
                    {stripCell(jointIndex, 1, delta.hi)}
                  </>
                ) : (
                  <>
                    {bar(jointIndex, delta.travel, FOLD_COLOR, 0,
                         `travel Δ (measured ${(entry.rom[1] - entry.rom[0]).toFixed(1)}° vs config ${(joint.rom[1] - joint.rom[0]).toFixed(1)}°)`)}
                    {stripCell(jointIndex, 0, delta.travel, 2)}
                  </>
                )}
                <text
                  transform={`rotate(-45 ${colX(jointIndex)} ${MARGIN.top + PLOT_H + 12})`}
                  x={colX(jointIndex)}
                  y={MARGIN.top + PLOT_H + 12}
                  textAnchor="end"
                  fontSize={8}
                  fill="var(--dim)"
                >
                  {joint.id}
                </text>
              </g>
            )
          })}
          {[...deltas.values()].some((d) => 'lo' in d) ? (
            <>
              <text
                x={MARGIN.left - 5}
                y={stripTop + STRIP_ROW_H / 2 + 3}
                textAnchor="end"
                fontSize={7}
                fill="var(--dimmer)"
              >
                Δlow
              </text>
              <text
                x={MARGIN.left - 5}
                y={stripTop + STRIP_ROW_H + STRIP_ROW_H / 2 + 3}
                textAnchor="end"
                fontSize={7}
                fill="var(--dimmer)"
              >
                Δhigh
              </text>
            </>
          ) : (
            <text
              x={MARGIN.left - 5}
              y={stripTop + STRIP_ROW_H + 3}
              textAnchor="end"
              fontSize={7}
              fill="var(--dimmer)"
            >
              Δtravel
            </text>
          )}
        </svg>
      </div>
    </div>
  )
}

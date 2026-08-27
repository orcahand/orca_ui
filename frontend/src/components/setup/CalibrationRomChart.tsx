// Hardstop-consistency chart: X = joints, Y = degrees. Per joint, the grey
// band is the config ROM, one thin bar per selected calibration run spans
// that run's measured ROM (hardstop to hardstop), and the accent tick is the
// live sensor angle — so magnet/hardstop drift shows as bars that disagree,
// and a mis-anchored sensor as a tick outside every bar.
//
// Two bar flavors: solid = absolute measured ROM from the encoder anchor
// pass (measured_rom_recorded). Translucent = span only, derived from the
// motor limits sampled at the hardstops (limit_recorded: motor travel ÷ the
// run's ratio) and anchored at the config lower stop — the sweep measured
// how FAR the joint travels but had no sensor to say where that travel sits,
// so only the bar's length is meaningful, not its position.

import { useMemo, useRef, useState } from 'react'
import type {
  CalibrationRun,
  JointInfo,
  SensorFrameEntry,
} from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { useThemeStore } from '../../theme/themeStore'

// Categorical series palettes (dataviz-validated against --bg per theme:
// adjacent CVD ΔE ≥ 8.4, normal-vision ΔE ≥ 19). Hue follows the run —
// index in the full run list, newest first — never its rank among the
// currently selected. Runs past the palette fold to muted grey.
export const SERIES_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
                             '#e87ba4', '#008300', '#4a3aa7', '#e34948']
export const SERIES_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500',
                            '#d55181', '#008300', '#9085e9', '#e66767']
export const FOLD_COLOR = 'var(--dimmer)'

const PLOT_H = 220
const MARGIN = { top: 8, right: 8, bottom: 64, left: 40 }
const COL_W = 44
const BAND_W = 18
const DEFAULT_SELECTED = 3
// Breathing room above/below the outermost value on the auto scale.
const PAD_DEG = 20
// One click of the manual expand/shrink buttons, per side.
const MANUAL_STEP_DEG = 15
const MANUAL_MIN_SPAN_DEG = 30

export interface JointRom {
  rom: [number, number]
  deviation: number | null
  // True when only the travel is measured (motor limits ÷ ratio) and the
  // interval is anchored at the config lower stop for display.
  spanOnly: boolean
}

export interface MagnetSample {
  flex: number
  extend: number
  rejected: boolean
}

export interface RomRun {
  key: string
  when: string
  simulated: boolean
  color: string
  roms: Map<string, JointRom>
  // Raw hardstop magnet counts, when the anchor pass sampled them — the
  // un-homed truth the raw view decodes through the CURRENT sensor frame.
  magnets: Map<string, MagnetSample>
}

export function extractRomRuns(
  runs: CalibrationRun[],
  dark: boolean,
  configRom: Map<string, [number, number]>,
): RomRun[] {
  const series = dark ? SERIES_DARK : SERIES_LIGHT
  const out: RomRun[] = []
  for (const run of runs) {
    const roms = new Map<string, JointRom>()
    const magnets = new Map<string, MagnetSample>()
    const ratios = new Map<string, number>()
    const limits = new Map<string, { lower?: number; upper?: number }>()
    for (const event of run.events) {
      if (
        (event.event === 'measured_rom_recorded' ||
          event.event === 'measured_rom_rejected') &&
        event.joint &&
        event.flex_count != null &&
        event.extend_count != null
      ) {
        magnets.set(event.joint, {
          flex: event.flex_count,
          extend: event.extend_count,
          rejected: event.event === 'measured_rom_rejected',
        })
      }
      if (event.event === 'measured_rom_recorded' && event.joint && event.rom) {
        roms.set(event.joint, {
          rom: event.rom,
          deviation: event.deviation_deg ?? null,
          spanOnly: false,
        })
      } else if (event.event === 'joint_calibrated' && event.joint &&
                 event.ratio) {
        ratios.set(event.joint, event.ratio)
      } else if (event.event === 'limit_recorded' && event.joint &&
                 event.limit != null && event.bound) {
        if (!limits.has(event.joint)) limits.set(event.joint, {})
        limits.get(event.joint)![event.bound] = event.limit
      }
    }
    // Joints without an absolute sensor ROM: motor travel ÷ ratio gives the
    // measured span in joint degrees, drawn from the config lower stop.
    for (const [joint, { lower, upper }] of limits) {
      const ratio = ratios.get(joint)
      const config = configRom.get(joint)
      if (roms.has(joint) || lower == null || upper == null ||
          !ratio || !config) continue
      const span = Math.abs(upper - lower) / ratio
      roms.set(joint, {
        rom: [config[0], config[0] + span],
        deviation: span - (config[1] - config[0]),
        spanOnly: true,
      })
    }
    if (roms.size === 0 && magnets.size === 0) continue
    out.push({
      key: run.started_at,
      when: run.finished_at,
      simulated: Boolean(run.simulated),
      color: series[out.length] ?? FOLD_COLOR,
      roms,
      magnets,
    })
  }
  return out
}

const COUNTS_PER_REV = 16384
const LSB_DEG = 360 / COUNTS_PER_REV

// A raw magnet count decoded through the CURRENT sensor frame — the same
// math the live stream uses, so raw-view bars and the live tick share a
// frame. A rigid magnet re-decodes each sweep's hardstop to the same angle;
// a slipping one walks.
export function decodeCount(count: number, frame: SensorFrameEntry): number {
  let delta =
    ((((count - frame.anchor_count) % COUNTS_PER_REV) + COUNTS_PER_REV) %
      COUNTS_PER_REV) *
    LSB_DEG
  if (delta > 180) delta -= 360
  return frame.polarity * delta + frame.anchor_angle_deg
}

export function fmtWhen(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo
  const step = [5, 10, 15, 30, 45, 90].find((s) => span / s <= 9) ?? 90
  const ticks: number[] = []
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t)
  return ticks
}

// One rendered interval, whatever the view derived it from.
interface Bar {
  lo: number
  hi: number
  faded: boolean
  // Raw view: where the flex-hardstop sample decodes to — capped on the bar
  // so magnet slip direction is readable.
  flexDeg?: number
  title: string
}

export function CalibrationRomChart({
  runs,
  frame,
}: {
  runs: CalibrationRun[]
  frame?: Record<string, SensorFrameEntry>
}) {
  const handInfo = useAppStore((s) => s.handInfo)
  const dark = useThemeStore((s) => s.theme) === 'dark'
  const romRuns = useMemo(() => {
    const configRom = new Map<string, [number, number]>(
      (handInfo?.joints ?? []).map((j) => [j.id, j.rom]),
    )
    return extractRomRuns(runs, dark, configRom)
  }, [runs, dark, handInfo])

  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(romRuns.slice(0, DEFAULT_SELECTED).map((r) => r.key)),
  )
  // Raw view: decode each run's hardstop magnet counts through TODAY's
  // sensor frame — un-homed, so magnet slip between sweeps is visible.
  const [rawView, setRawView] = useState(false)
  const tickRefs = useRef(new Map<string, SVGLineElement>())
  // Live-angle extremes, rounded outward to 10° (the rounding doubles as
  // hysteresis so the scale re-renders only on real change, not jitter).
  const [liveExt, setLiveExt] = useState<[number, number] | null>(null)
  const liveCheckedAt = useRef(0)
  // Manual Y mode: freeze the current domain, then expand/shrink by button.
  const [manualDomain, setManualDomain] = useState<[number, number] | null>(null)

  const rawAvailable =
    frame != null &&
    Object.keys(frame).length > 0 &&
    romRuns.some((r) => r.magnets.size > 0)

  // Joints in hand order, restricted to those any run measured or sampled.
  const joints: JointInfo[] = useMemo(() => {
    if (!handInfo) return []
    const measured = new Set(
      romRuns.flatMap((r) => [...r.roms.keys(), ...r.magnets.keys()]),
    )
    return handInfo.joints.filter((j) => measured.has(j.id))
  }, [handInfo, romRuns])

  const shown = romRuns.filter((r) => selected.has(r.key))

  // The bars each selected run contributes per joint, in the active view.
  const bars = new Map<string, Map<string, Bar>>()
  for (const run of shown) {
    const perJoint = new Map<string, Bar>()
    for (const joint of joints) {
      if (rawView) {
        const sample = run.magnets.get(joint.id)
        const jointFrame = frame?.[joint.id]
        if (!sample || !jointFrame) continue
        const flexDeg = decodeCount(sample.flex, jointFrame)
        const extendDeg = decodeCount(sample.extend, jointFrame)
        perJoint.set(joint.id, {
          lo: Math.min(flexDeg, extendDeg),
          hi: Math.max(flexDeg, extendDeg),
          faded: sample.rejected,
          flexDeg,
          title:
            `${joint.id} · ${fmtWhen(run.when)}\n` +
            `hardstops decoded in today's sensor frame (un-homed):\n` +
            `flex ${flexDeg.toFixed(1)}° (magnet @${sample.flex})\n` +
            `extend ${extendDeg.toFixed(1)}° (magnet @${sample.extend})` +
            (sample.rejected ? `\nthis sweep's ROM was REJECTED` : ''),
        })
      } else {
        const entry = run.roms.get(joint.id)
        if (!entry) continue
        const [lo, hi] = entry.rom
        const dev = entry.deviation
        perJoint.set(joint.id, {
          lo,
          hi,
          faded: entry.spanOnly,
          title:
            `${joint.id} · ${fmtWhen(run.when)}\n` +
            (entry.spanOnly
              ? `measured travel ${(hi - lo).toFixed(1)}° ` +
                `(motor limits ÷ ratio; drawn from the config ` +
                `lower stop — only the length is measured)` +
                (dev != null
                  ? `\nspan ${dev >= 0 ? '+' : ''}${dev.toFixed(1)}° vs config`
                  : '')
              : `measured ROM [${lo.toFixed(1)}, ${hi.toFixed(1)}]°` +
                (dev != null
                  ? `\nlower hardstop ${dev >= 0 ? '+' : ''}` +
                    `${dev.toFixed(1)}° vs config`
                  : '')),
        })
      }
    }
    bars.set(run.key, perJoint)
  }

  // Auto Y domain: config ROMs, every bar in the active view, AND the live
  // sensor extremes — a mis-anchored joint reading −100° must be on scale,
  // that outlier is the point of the chart. Grows and shrinks as the live
  // values move; PAD_DEG of margin above and below.
  let autoLo = Infinity
  let autoHi = -Infinity
  for (const joint of joints) {
    autoLo = Math.min(autoLo, joint.rom[0])
    autoHi = Math.max(autoHi, joint.rom[1])
  }
  for (const perJoint of bars.values()) {
    for (const bar of perJoint.values()) {
      autoLo = Math.min(autoLo, bar.lo)
      autoHi = Math.max(autoHi, bar.hi)
    }
  }
  if (liveExt) {
    autoLo = Math.min(autoLo, liveExt[0])
    autoHi = Math.max(autoHi, liveExt[1])
  }
  if (!Number.isFinite(autoLo)) {
    autoLo = -90
    autoHi = 90
  }
  autoLo -= PAD_DEG
  autoHi += PAD_DEG
  const [yLo, yHi] = manualDomain ?? [autoLo, autoHi]

  const y = (deg: number) =>
    MARGIN.top + ((yHi - deg) / (yHi - yLo)) * PLOT_H
  const colX = (index: number) => MARGIN.left + index * COL_W + COL_W / 2

  // Live sensor angles, painted straight onto the SVG — no React re-render.
  // Every ~500 ms the extremes feed back into React state so the auto scale
  // can follow them.
  useStreamFrame((frames) => {
    let lo = Infinity
    let hi = -Infinity
    for (const joint of joints) {
      const measured = frames.joints.measured[joint.id]
      if (measured !== undefined) {
        lo = Math.min(lo, measured)
        hi = Math.max(hi, measured)
      }
      const tick = tickRefs.current.get(joint.id)
      if (!tick) continue
      if (measured === undefined || measured < yLo || measured > yHi) {
        tick.setAttribute('visibility', 'hidden')
        continue
      }
      const py = y(measured).toFixed(1)
      tick.setAttribute('y1', py)
      tick.setAttribute('y2', py)
      tick.setAttribute('visibility', 'visible')
    }
    const now = performance.now()
    if (now - liveCheckedAt.current < 500) return
    liveCheckedAt.current = now
    const next: [number, number] | null = Number.isFinite(lo)
      ? [Math.floor(lo / 10) * 10, Math.ceil(hi / 10) * 10]
      : null
    setLiveExt((prev) =>
      prev === next ||
      (prev && next && prev[0] === next[0] && prev[1] === next[1])
        ? prev
        : next,
    )
  })

  if (romRuns.length === 0 || joints.length === 0) return null

  const width = MARGIN.left + joints.length * COL_W + MARGIN.right
  const height = MARGIN.top + PLOT_H + MARGIN.bottom
  const ticks = niceTicks(yLo, yHi)

  // Side-by-side run bars, shrunk to fit the column when many are selected.
  const barW = Math.max(2, Math.min(4, Math.floor((COL_W - 8) / Math.max(1, shown.length)) - 1))
  const groupW = shown.length * (barW + 2) - 2
  const barX = (jointIndex: number, runIndex: number) =>
    colX(jointIndex) - groupW / 2 + runIndex * (barW + 2)

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <div style={{ margin: '8px 0' }}>
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
        <button
          className="btn btn-secondary"
          style={{ fontSize: 9, padding: '1px 6px' }}
          onClick={() => setSelected(new Set(romRuns.map((r) => r.key)))}
        >
          show all
        </button>
        <button
          className="btn btn-secondary"
          style={{ fontSize: 9, padding: '1px 6px' }}
          onClick={() => setSelected(new Set())}
        >
          none
        </button>
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            style={{ fontSize: 9, padding: '1px 6px' }}
            title={
              manualDomain
                ? 'back to auto: the scale follows the data again'
                : 'freeze the scale, then widen or tighten it by hand'
            }
            onClick={() =>
              setManualDomain((prev) => (prev ? null : [yLo, yHi]))
            }
          >
            Y: {manualDomain ? 'manual' : 'auto'}
          </button>
          <button
            className="btn btn-secondary"
            style={{ fontSize: 9, padding: '1px 6px' }}
            disabled={!rawAvailable}
            title={
              rawAvailable
                ? rawView
                  ? 'homed view: measured ROM pinned to the config upper ' +
                    'stop (only the span is measured)'
                  : "raw view: each sweep's hardstop magnet counts decoded " +
                    "in TODAY's sensor frame — un-homed, so magnet slip " +
                    'between sweeps shows as bars that walk'
                : 'needs runs with the joint-sensor pass (magnet counts) ' +
                  'and a current sensor anchor'
            }
            onClick={() => setRawView((v) => !v)}
          >
            view: {rawView ? 'raw' : 'homed'}
          </button>
          {manualDomain && (
            <>
              <button
                className="btn btn-secondary"
                style={{ fontSize: 9, padding: '1px 6px' }}
                title={`widen by ${MANUAL_STEP_DEG}° per side`}
                onClick={() =>
                  setManualDomain((prev) =>
                    prev
                      ? [prev[0] - MANUAL_STEP_DEG, prev[1] + MANUAL_STEP_DEG]
                      : prev,
                  )
                }
              >
                −
              </button>
              <button
                className="btn btn-secondary"
                style={{ fontSize: 9, padding: '1px 6px' }}
                title={`tighten by ${MANUAL_STEP_DEG}° per side`}
                onClick={() =>
                  setManualDomain((prev) =>
                    !prev ||
                    prev[1] - prev[0] - 2 * MANUAL_STEP_DEG <
                      MANUAL_MIN_SPAN_DEG
                      ? prev
                      : [prev[0] + MANUAL_STEP_DEG, prev[1] - MANUAL_STEP_DEG],
                  )
                }
              >
                +
              </button>
            </>
          )}
        </span>
        {romRuns.map((run) => (
          <label
            key={run.key}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              cursor: 'pointer',
              color: selected.has(run.key) ? 'var(--dim)' : 'var(--dimmer)',
            }}
          >
            <input
              type="checkbox"
              checked={selected.has(run.key)}
              onChange={() => toggle(run.key)}
            />
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: run.color,
                display: 'inline-block',
              }}
            />
            {fmtWhen(run.when)}
            {run.simulated ? ' (sim)' : ''}
          </label>
        ))}
        <span style={{ color: 'var(--dimmer)' }}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 8,
              background: 'var(--panel-border-strong)',
              borderRadius: 2,
              verticalAlign: -1,
              marginRight: 4,
            }}
          />
          config ROM
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 2,
              background: 'var(--accent)',
              verticalAlign: 2,
              margin: '0 4px 0 12px',
            }}
          />
          live sensor angle
          <span style={{ marginLeft: 12 }}>
            {rawView
              ? 'bars = hardstop magnet samples decoded in today’s ' +
                'sensor frame (cap marks the flex sample) · translucent = ' +
                'that sweep’s ROM was rejected'
              : 'solid = sensor-measured ROM (homed: pinned to the config ' +
                'upper stop) · translucent = travel only (anchored at the ' +
                'config lower stop)'}
          </span>
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
                {tick}°
              </text>
            </g>
          ))}
          {joints.map((joint, jointIndex) => (
            <g key={joint.id}>
              <rect
                x={colX(jointIndex) - BAND_W / 2}
                y={y(joint.rom[1])}
                width={BAND_W}
                height={Math.max(1, y(joint.rom[0]) - y(joint.rom[1]))}
                rx={2}
                fill="var(--panel-border-strong)"
              >
                <title>
                  {`${joint.id} config ROM [${joint.rom[0]}, ${joint.rom[1]}]°`}
                </title>
              </rect>
              {shown.map((run, runIndex) => {
                const bar = bars.get(run.key)?.get(joint.id)
                if (!bar) return null
                const x = barX(jointIndex, runIndex)
                return (
                  <g key={run.key}>
                    <rect
                      x={x}
                      y={y(bar.hi)}
                      width={barW}
                      height={Math.max(1, y(bar.lo) - y(bar.hi))}
                      rx={1}
                      fill={run.color}
                      opacity={bar.faded ? 0.45 : 1}
                    >
                      <title>{bar.title}</title>
                    </rect>
                    {bar.flexDeg !== undefined && (
                      <rect
                        x={x - 1}
                        y={y(bar.flexDeg) - 1}
                        width={barW + 2}
                        height={2}
                        fill={run.color}
                      />
                    )}
                  </g>
                )
              })}
              <line
                ref={(el) => {
                  if (el) tickRefs.current.set(joint.id, el)
                  else tickRefs.current.delete(joint.id)
                }}
                x1={colX(jointIndex) - BAND_W / 2 - 2}
                x2={colX(jointIndex) + BAND_W / 2 + 2}
                y1={MARGIN.top}
                y2={MARGIN.top}
                stroke="var(--accent)"
                strokeWidth={2}
                visibility="hidden"
              />
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
          ))}
        </svg>
      </div>
    </div>
  )
}

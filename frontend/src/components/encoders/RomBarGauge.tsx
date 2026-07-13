// Bipolar ROM bar: the fill is anchored at the joint's zero mark and grows
// toward the measured angle, so crossing zero shrinks to nothing and regrows
// on the other side — no jumps. Target caret overlaid; fill tinted by
// tracking error when a target exists.

import { useRef } from 'react'
import type { JointInfo } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { COLORS } from '../../theme/tokens'

const W = 100 // viewBox width units
const ERROR_WARN_DEG = 3
const ERROR_BAD_DEG = 8
const STALE_MS = 500

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function RomBarGauge({ joint }: { joint: JointInfo }) {
  const [min, max] = joint.rom
  const span = max - min
  // Encoder present but unusable (no anchor) or excluded from the feedback
  // loop (incomplete calibration): the joint runs open-loop — flag the row.
  const degraded =
    joint.encoder_calibrated === false || joint.loop_controlled === false
  const frac = (v: number) => clamp((v - min) / span, 0, 1)
  const zeroFrac = frac(0)

  const fillRef = useRef<SVGRectElement>(null)
  const targetRef = useRef<SVGLineElement>(null)
  const valueRef = useRef<HTMLSpanElement>(null)
  const groupRef = useRef<SVGSVGElement>(null)

  useStreamFrame((frames) => {
    const measured = frames.joints.measured[joint.id]
    if (measured === undefined) return

    const fill = fillRef.current
    if (fill) {
      const measuredFrac = frac(measured)
      const x = Math.min(zeroFrac, measuredFrac) * W
      const width = Math.abs(measuredFrac - zeroFrac) * W
      fill.setAttribute('x', x.toFixed(2))
      fill.setAttribute('width', Math.max(width, 0.001).toFixed(2))

      const target = frames.joints.target[joint.id]
      let color: string = COLORS.accent
      if (target !== undefined) {
        const error = Math.abs(measured - target)
        color =
          error < ERROR_WARN_DEG
            ? COLORS.accent
            : error < ERROR_BAD_DEG
              ? COLORS.warn
              : COLORS.err
      }
      fill.setAttribute('fill', color)
    }

    const targetTick = targetRef.current
    if (targetTick) {
      const target = frames.joints.target[joint.id]
      if (target !== undefined) {
        const x = (frac(target) * W).toFixed(2)
        targetTick.setAttribute('x1', x)
        targetTick.setAttribute('x2', x)
        targetTick.setAttribute('visibility', 'visible')
      } else {
        targetTick.setAttribute('visibility', 'hidden')
      }
    }

    if (valueRef.current) {
      valueRef.current.textContent = `${measured >= 0 ? '+' : ''}${measured.toFixed(1)}°`
    }

    // Stale fade: encoder data older than 500 ms dims the fill.
    if (groupRef.current) {
      const stale = Date.now() - frames.joints.tMeasured > STALE_MS
      groupRef.current.style.opacity = stale ? '0.3' : '1'
    }
  })

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 10,
        padding: '2px 0',
      }}
    >
      <span style={{ width: 84, color: 'var(--text)', textAlign: 'right' }}>
        {joint.id}
      </span>
      <span style={{ width: 30, color: 'var(--dimmer)', fontSize: 9, textAlign: 'right' }}>
        {min.toFixed(0)}
      </span>
      <svg
        ref={groupRef}
        viewBox={`0 0 ${W} 14`}
        preserveAspectRatio="none"
        style={{
          flex: 1,
          height: 14,
          display: 'block',
          transition: 'opacity 0.3s',
        }}
      >
        <rect
          x={0}
          y={2}
          width={W}
          height={10}
          fill={degraded ? 'rgba(212,135,138,0.12)' : 'rgba(255,255,255,0.04)'}
          stroke={degraded ? COLORS.err : 'rgba(255,255,255,0.08)'}
          strokeWidth={degraded ? 0.8 : 0.4}
        />
        <rect ref={fillRef} x={zeroFrac * W} y={2} width={0.001} height={10}
              fill={COLORS.accent} opacity={0.55} />
        <line
          x1={zeroFrac * W}
          x2={zeroFrac * W}
          y1={2}
          y2={12}
          stroke="#5f718b"
          strokeWidth={0.7}
        />
        <line
          ref={targetRef}
          x1={zeroFrac * W}
          x2={zeroFrac * W}
          y1={0}
          y2={14}
          stroke="#dfe3e8"
          strokeWidth={0.9}
          visibility="hidden"
        />
      </svg>
      <span style={{ width: 30, color: 'var(--dimmer)', fontSize: 9 }}>
        {max > 0 ? `+${max.toFixed(0)}` : max.toFixed(0)}
      </span>
      {joint.encoder_calibrated === false ? (
        <span
          title="This joint's encoder streams raw counts, but no calibration
anchor exists to convert them into an angle. It runs on open-loop motor
control. Run calibration with joint feedback to record the anchors."
          style={{
            width: 52,
            color: 'var(--err)',
            fontSize: 9,
            textAlign: 'right',
            cursor: 'help',
          }}
        >
          no cal
        </span>
      ) : joint.loop_controlled === false ? (
        <span
          title="This joint's calibration is incomplete (missing motor limits,
ratio, or a trustworthy encoder anchor), so the feedback loop skipped it —
it runs on open-loop motor control until recalibrated. The angle shown may
be wrong."
          style={{
            width: 52,
            color: 'var(--err)',
            fontSize: 9,
            textAlign: 'right',
            cursor: 'help',
          }}
        >
          open loop
        </span>
      ) : (
        <span
          ref={valueRef}
          style={{ width: 52, color: 'var(--text)', fontWeight: 600, textAlign: 'right' }}
        >
          --
        </span>
      )}
    </div>
  )
}

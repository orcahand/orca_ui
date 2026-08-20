// Resultant-force dial per finger: ring + moving dot (direction from
// atan2(fy,fx), radius/opacity/color from magnitude) + Fx/Fy/Fz/|F| numerics.
// Port of the original updateForces (script.js lines 753–790).

import { useRef } from 'react'
import type { Finger } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { usePalette } from '../../theme/themeStore'
import { MAX_FORCE_SCALE } from '../../theme/tokens'

const MIN_CIRCLE_RADIUS = 2
const MAX_CIRCLE_RADIUS = 40
const VISUALIZATION_RADIUS = 70

export function ForceDial({ finger }: { finger: Finger }) {
  const { dial } = usePalette()
  const dotRef = useRef<SVGCircleElement>(null)
  const fxRef = useRef<HTMLSpanElement>(null)
  const fyRef = useRef<HTMLSpanElement>(null)
  const fzRef = useRef<HTMLSpanElement>(null)
  const magRef = useRef<HTMLSpanElement>(null)
  const lastT = useRef(0)
  const lastText = useRef(0)

  useStreamFrame((frames) => {
    const forces = frames.tactile.forces?.[finger]
    if (!forces || frames.tactile.tForces === lastT.current) return
    lastT.current = frames.tactile.tForces

    const [fx, fy, fz] = forces
    const magnitude = Math.sqrt(fx * fx + fy * fy + fz * fz)

    const dot = dotRef.current
    if (dot) {
      const centerX = 100
      const centerY = 100
      const normalized = Math.min(magnitude / MAX_FORCE_SCALE, 1)
      const radius =
        MIN_CIRCLE_RADIUS + normalized * (MAX_CIRCLE_RADIUS - MIN_CIRCLE_RADIUS)
      const angle = Math.atan2(fy, fx)
      const distance = Math.min(
        normalized * VISUALIZATION_RADIUS,
        VISUALIZATION_RADIUS,
      )
      dot.setAttribute('cx', String(centerX + distance * Math.cos(angle)))
      dot.setAttribute('cy', String(centerY - distance * Math.sin(angle)))
      dot.setAttribute('r', String(radius))
      dot.setAttribute('opacity', String(Math.min(0.3 + normalized * 0.7, 1)))
      dot.setAttribute('fill', magnitude > 1 ? dial.high : dial.low)
    }

    // Text at ~10 Hz to avoid flicker.
    const now = performance.now()
    if (now - lastText.current > 100) {
      lastText.current = now
      if (fxRef.current) fxRef.current.textContent = fx.toFixed(1)
      if (fyRef.current) fyRef.current.textContent = fy.toFixed(1)
      if (fzRef.current) fzRef.current.textContent = fz.toFixed(1)
      if (magRef.current) magRef.current.textContent = magnitude.toFixed(1)
    }
  })

  return (
    <div className="force-visualization">
      <div className="force-label">
        {finger.charAt(0).toUpperCase() + finger.slice(1)}
      </div>
      <svg className="force-arrow" viewBox="0 0 200 200">
        <circle
          cx={100}
          cy={100}
          r={80}
          fill="none"
          stroke={dial.ring}
          strokeWidth={1}
        />
        <line x1={100} y1={20} x2={100} y2={180} stroke={dial.cross} />
        <line x1={20} y1={100} x2={180} y2={100} stroke={dial.cross} />
        <circle ref={dotRef} cx={100} cy={100} r={2} fill={dial.low} opacity={0.3} />
      </svg>
      <div className="force-values">
        <div>
          Fx: <span ref={fxRef}>0.0</span> N
        </div>
        <div>
          Fy: <span ref={fyRef}>0.0</span> N
        </div>
        <div>
          Fz: <span ref={fzRef}>0.0</span> N
        </div>
        <div className="force-magnitude">
          |F| = <span ref={magRef}>0.0</span> N
        </div>
      </div>
    </div>
  )
}

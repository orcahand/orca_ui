// The plate from above, camera at the top. Each stop is a dot on the travel
// (counter-clockwise from the hard stop at 0°); the needle is the plate's
// angle (the motor's, when it is connected), and the object's square turns
// with it, its fully tiled sides drawn heavy and side 0 labelled. After the
// rotation solve, each stop carries its correction as a short bar.

import type { PhotoEntry } from './api'

const R = 84 // stop ring
const PLATE = 66
const HALF = 22 // object half width, to scale with the plate
const WEAK = 32 // corners below this: a weak photo
const BAR_PX_PER_DEG = 18

// Angle counter-clockwise from "toward the camera" (up) -> svg point.
function at(deg: number, r: number): [number, number] {
  const a = (deg * Math.PI) / 180
  return [-Math.sin(a) * r, -Math.cos(a) * r]
}

function arcPath(from: number, to: number, r: number) {
  const [x0, y0] = at(from, r)
  const [x1, y1] = at(to, r)
  const large = Math.abs(to - from) > 180 ? 1 : 0
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${large} 0 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

export function StopDial({
  stops,
  travel,
  side0Stop,
  taken,
  current,
  angle,
  onPick,
  object = true,
  corrections,
}: {
  stops: number[]
  travel: number
  side0Stop: number
  taken: Map<number, PhotoEntry>
  current: number | null
  angle: number | null // where the plate is; null: at the selected stop
  onPick?: (index: number) => void
  object?: boolean // the calibration object is on the plate (not the hand)
  corrections?: Record<string, number> | null // stop -> deg, from the rotation solve
}) {
  const plate = angle ?? (current !== null ? stops[current] : 0)
  // Side s faces outward at plate angle -side0Stop + 90 s; side 0 faces the camera at side0Stop.
  const face = (s: number) => plate - side0Stop + 90 * s
  const sides = [0, 1, 2, 3].map((s) => {
    const [ax, ay] = at(face(s) - 45, HALF * Math.SQRT2)
    const [bx, by] = at(face(s) + 45, HALF * Math.SQRT2)
    return { s, ax, ay, bx, by }
  })
  const [lx, ly] = at(face(0), HALF + 9)
  const [nx, ny] = at(plate, PLATE - 4)
  const [sx0, sy0] = at(-3, R - 9)
  const [sx1, sy1] = at(-3, R + 9)
  const corr = (deg: number) => {
    if (!corrections) return null
    const hit = Object.entries(corrections).find(([k]) => Math.abs(Number(k) - deg) < 1e-6)
    return hit ? hit[1] : null
  }
  return (
    <svg className="visual-cal-dial" viewBox="-134 -130 268 256" role="img" aria-label="Plate stops seen from above">
      <g className="dial-camera">
        <path d="M-9 -126H9L0 -114Z" />
        <text x="16" y="-116">camera</text>
      </g>
      <circle className="dial-plate" r={PLATE} />
      <path className="dial-travel" d={arcPath(0, travel, R)} />
      <path className="dial-gap" d={arcPath(travel, 360, R)} />
      <line className="dial-stop" x1={sx0} y1={sy0} x2={sx1} y2={sy1}>
        <title>hard stop · 0°</title>
      </line>
      <line className="dial-needle" x1={0} y1={0} x2={nx} y2={ny} />
      {object && (
        <g className="dial-object">
          {sides.map(({ s, ax, ay, bx, by }) => (
            <line key={s} className={s % 2 === 0 ? 'full' : ''} x1={ax} y1={ay} x2={bx} y2={by} />
          ))}
          <text x={lx} y={ly + 3}>0</text>
        </g>
      )}
      {stops.map((deg, i) => {
        const [x, y] = at(deg, R)
        const photo = taken.get(deg)
        const state = photo ? (photo.corners >= WEAK ? 'ok' : 'weak') : ''
        const label = deg % 45 === 0 || i === current
        const c = corr(deg)
        const [tx, ty] = at(deg, R + (c !== null ? 33 : 17))
        const [b0x, b0y] = at(deg, R + 7)
        const [b1x, b1y] = at(deg, R + 7 + Math.max(2, Math.min(18, Math.abs(c ?? 0) * BAR_PX_PER_DEG)))
        const tip = [
          `${deg}°`,
          photo ? `${photo.tiles} tiles, ${photo.corners} corners` : 'no photo yet',
          c !== null ? `${c >= 0 ? '+' : ''}${c.toFixed(2)}° off` : '',
        ].filter(Boolean)
        return (
          <g
            key={deg}
            className={`dial-dot ${state}${i === current ? ' current' : ''}${onPick ? ' pick' : ''}`}
            onClick={onPick ? () => onPick(i) : undefined}
          >
            <title>{tip.join(' · ')}</title>
            <circle cx={x} cy={y} r={11} className="hit" />
            <circle cx={x} cy={y} r={i === current ? 6 : 4} />
            {c !== null && <line className={`dial-corr${Math.abs(c) > 1 ? ' warn' : ''}`} x1={b0x} y1={b0y} x2={b1x} y2={b1y} />}
            {label && (
              <text x={tx} y={ty + 3}>
                {deg}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

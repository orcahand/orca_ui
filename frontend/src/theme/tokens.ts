// Palette mirror for canvas/three/uPlot consumers (theme.css is the CSS side).

export const COLORS = {
  bg: '#1a1c2a',
  text: '#dfe3e8',
  muted: '#9faab9',
  dim: '#7f8ea2',
  dimmer: '#5f718b',
  accent: '#22d3ee',
  ok: '#34d399',
  warn: '#c8a870',
  err: '#d4878a',
  purple: '#a78bfa',
  taxelIdle: '#1a1a1a',
} as const

// ORCA gradient stops (getArrowColor2D 'orca' scheme): #474f5e → #e5e7eb
export const ORCA_GRADIENT: [number, number, number][] = [
  [71, 79, 94],
  [127, 142, 162],
  [191, 199, 209],
  [229, 231, 235],
]

// Per-taxel normalization, keyed by sensor model. 25.5 N is the *encoding*
// full scale (fz is an unsigned byte * 0.1 N) — not what a taxel actually
// reaches. Measured on orcahand-full-right under a hard fingertip press:
//
//   index 10.4 N   middle 11.8 N   ring 10.4 N    (87-taxel part, identical
//                                                  peaks and hot-taxel indices)
//   thumb 21.4 N                                  (51-taxel part)
//   pinky 28.7 N — railed fx at 12.7 and fz at 25.5, i.e. saturating
//
// Each model normalizes against its own reach so it uses the full brightness
// range. The trade-off is deliberate: equal brightness across two different
// fingers does NOT mean equal force. Re-measure with
// scripts/measure_taxels.py if the sensor hardware changes.
//
// Pinky keeps the encoding full scale because it already rails there; the
// others are set just above their measured peak so a hard press reads white.
export const MAX_TAXEL_FORCE_BY_FINGER: Record<string, number> = {
  thumb: 22,
  index: 12,
  middle: 12,
  ring: 12,
  pinky: 25.5,
}
// Fallback for an unrecognised finger: the encoding full scale, which
// under-reads rather than blowing out to white.
export const MAX_TAXEL_FORCE = 25.5

export function maxTaxelForce(finger: string): number {
  return MAX_TAXEL_FORCE_BY_FINGER[finger] ?? MAX_TAXEL_FORCE
}

export const MAX_FORCE_SCALE = 10 // N; resultant dial normalization

// Zero-force taxel shade in the magnitude ramp. Matches COLORS.taxelIdle so an
// unloaded taxel reads the same in every display mode; the ramp used to floor
// at 60, which spent a quarter of the range before any force was applied.
export const TAXEL_GRAY_FLOOR = 26
export const TAXEL_GRAY_SPAN = 229 // floor + span = 255 at full scale

// Force-scale constants for the tactile displays. Colors used to live here
// too; they are per-theme now and moved to palette.ts.

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

// Resultant normalization, shared by the 2D dial and the 3D resultant arrow.
// Unlike the taxels this is NOT per-model: the resultant is a single reading
// of one byte per axis, so 25.5 N (uint8 fz * 0.1 N) is its full scale on
// every sensor. Normalizing against 10 N pinned the dial at the edge well
// before the sensor ran out of range.
export const MAX_FORCE_SCALE = 25.5

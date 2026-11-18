// Finding which bus id sits in a tower slot: every motor released, the
// operator turns the one in the armed slot by hand, and the shaft that moved
// — clearly, and alone — is the answer. Then the slot map becomes the motor
// numbers the bench config stores.

import type { BenchMotor } from '../benchStore'

// One shaft must have turned this far from where it was when the slot was
// armed while every other one stayed within STILL_DEG.
export const TURN_DEG = 7
export const STILL_DEG = 4

export interface Movement {
  id: number
  deg: number
}

/** Every motor's distance from its baseline, furthest first. */
export function movements(
  baseline: Record<string, number>,
  now: Record<string, number>,
): Movement[] {
  const out: Movement[] = []
  for (const [id, from] of Object.entries(baseline)) {
    const at = now[id]
    if (at === undefined || Number.isNaN(at) || Number.isNaN(from)) continue
    out.push({ id: Number(id), deg: Math.abs(at - from) })
  }
  return out.sort((a, b) => b.deg - a.deg)
}

/** The bus id turned by hand, or null while it is not yet unambiguous. */
export function turnedMotor(moved: Movement[]): number | null {
  const [first, second] = moved
  if (!first || first.deg < TURN_DEG) return null
  return second && second.deg >= STILL_DEG ? null : first.id
}

/** When more than one shaft moved: every one that did, for the operator to pick from. */
export function candidates(moved: Movement[]): Movement[] {
  const [first, second] = moved
  if (!first || first.deg < TURN_DEG || !second || second.deg < STILL_DEG) return []
  return moved.filter((m) => m.deg >= STILL_DEG)
}

/** Slot → bus id, as the bench numbers its motors now. */
export function slotsOf(motors: BenchMotor[], slotCount: number): Record<number, number> {
  const out: Record<number, number> = {}
  for (const m of motors) if (m.number >= 1 && m.number <= slotCount) out[m.number] = m.id
  return out
}

/** Put `id` in `slot`, taking it out of any other; whoever was there becomes unplaced. */
export function place(
  slots: Record<number, number>,
  slot: number,
  id: number,
): Record<number, number> {
  const next: Record<number, number> = {}
  for (const [s, m] of Object.entries(slots)) if (m !== id) next[Number(s)] = m
  next[slot] = id
  return next
}

/**
 * The bench's (bus id, number) set for a slot map: placed motors are
 * numbered by their slot, unplaced ones take the lowest numbers past the
 * tower so they never claim a slot they are not in.
 */
export function assignmentsFor(
  motors: BenchMotor[],
  slots: Record<number, number>,
  slotCount: number,
): { id: number; number: number }[] {
  const slotOfId = new Map(Object.entries(slots).map(([s, id]) => [id, Number(s)]))
  let spare = slotCount + 1
  return motors
    .map((m) => ({ id: m.id, number: slotOfId.get(m.id) ?? spare++ }))
    .sort((a, b) => a.number - b.number)
}

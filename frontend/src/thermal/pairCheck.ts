// Checking that two motors really are coupled: wiggle one while the other
// is released, and watch the released shaft. Each motor of the pair takes a
// turn as the mover — the step one way, the step the other, back to where
// it was — and the partner's position is read at both ends. The step is the
// operator's (15° by default: backlash and a soft coupling swallow a small
// one), the "followed" threshold a share of it. A partner that follows is
// coupled; the sign it follows with says whether the same command turns the
// two shafts the same way (then they must be driven opposed to load each
// other) or opposite ways (then the same sign already opposes). Uses the
// console's jog path, so the torque gate, the step cap and the e-stop all
// apply; the partner's hold is restored whatever happens.

import { api } from '../api/rest'
import type { MotorPair } from './thermalStore'

export const DEFAULT_STEP_DEG = 15
export const MIN_STEP_DEG = 1
export const MAX_STEP_DEG = 45 // the backend's direct-move step cap
const SETTLE_MS = 600
const DEG = Math.PI / 180
// A released shaft that moved less than this share of the step (at least
// 0.6°) did not follow.
const FOLLOW_SHARE = 0.3
const FOLLOW_MIN_DEG = 0.6

export interface PairCheckResult {
  ok: boolean
  // +1: the partner turns the same way as the mover; -1: the opposite way;
  // 0: it did not follow.
  sense: 1 | -1 | 0
  // Degrees the partner moved while the mover made its 2° steps, per leg.
  followed: { mover: number; partner: number; deg: number }[]
  message: string
  error?: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function positions(): Promise<Map<number, number>> {
  const snapshot = await api.motorsDirect()
  return new Map(snapshot.motors.map((m) => [m.id, m.position / DEG]))
}

async function leg(mover: number, partner: number, sign: 1 | -1, step: number): Promise<number> {
  const before = await positions()
  const from = before.get(mover)
  if (from === undefined) throw new Error(`motor ${mover} not on the bus`)
  await api.motorsDirectPosition(mover, (from + sign * step) * DEG)
  await sleep(SETTLE_MS)
  const at = await positions()
  const moved = (at.get(partner) ?? NaN) - (before.get(partner) ?? NaN)
  const moverMoved = (at.get(mover) ?? NaN) - from
  await api.motorsDirectPosition(mover, from * DEG)
  await sleep(SETTLE_MS)
  // Report the partner's move relative to the mover's actual move, so a
  // mover held back by friction still gives a clean sign.
  return moverMoved !== 0 && Number.isFinite(moverMoved) ? (moved * Math.sign(moverMoved)) : moved * sign
}

export async function checkPair(
  pair: MotorPair,
  label: (id: number) => string,
  step = DEFAULT_STEP_DEG,
): Promise<PairCheckResult> {
  const followed: PairCheckResult['followed'] = []
  const followMin = Math.max(FOLLOW_MIN_DEG, FOLLOW_SHARE * step)
  const restore: number[] = []
  try {
    await api.motorsDirectMode(true)
    for (const [mover, partner] of [
      [pair.a, pair.b],
      [pair.b, pair.a],
    ] as const) {
      await api.motorTorque(partner, false)
      restore.push(partner)
      try {
        for (const sign of [1, -1] as const) {
          const deg = await leg(mover, partner, sign, step)
          followed.push({ mover, partner, deg })
        }
      } finally {
        await api.motorTorque(partner, true)
        restore.pop()
      }
    }
  } catch (error) {
    for (const id of restore) await api.motorTorque(id, true).catch(() => undefined)
    await api.motorsDirectMode(false).catch(() => undefined)
    return {
      ok: false,
      sense: 0,
      followed,
      message: 'check failed',
      error: String((error as Error).message ?? error),
    }
  }
  await api.motorsDirectMode(false).catch(() => undefined)

  const legs = followed.filter((f) => Number.isFinite(f.deg))
  const mean = legs.length ? legs.reduce((s, f) => s + f.deg, 0) / legs.length : 0
  const consistent = legs.every((f) => Math.abs(f.deg) >= followMin && Math.sign(f.deg) === Math.sign(mean))
  if (!consistent || Math.abs(mean) < followMin) {
    const weak = legs.filter((f) => Math.abs(f.deg) < followMin)
    return {
      ok: false,
      sense: 0,
      followed,
      message:
        weak.length === legs.length
          ? `not coupled: ${label(pair.b)} did not follow ${label(pair.a)} and vice versa`
          : `loose: the partner followed in only ${legs.length - weak.length} of ${legs.length} moves`,
    }
  }
  const sense: 1 | -1 = mean > 0 ? 1 : -1
  return {
    ok: true,
    sense,
    followed,
    message:
      sense > 0
        ? `coupled, same direction (${Math.abs(mean).toFixed(1)}° of ${step}°) → drive opposed`
        : `coupled, opposite directions (${Math.abs(mean).toFixed(1)}° of ${step}°) → same sign already opposes`,
  }
}

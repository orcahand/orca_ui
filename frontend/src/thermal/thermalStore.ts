// Thermal mode state that is the operator's: the waveform and the run's
// limits, which motors are coupled shaft to shaft (each the other's load),
// whether the partner pushes opposed or the same way, when a pair last
// passed its coupling check, and which pairs are in the test. Kept by the
// backend beside the bench config (GET/PUT /api/thermal/setup), so the
// pairing follows the bench, not the browser.

import { create } from 'zustand'
import { api } from '../api/rest'
import type { ThermalLoad, ThermalSetupStored, ThermalWaveform } from '../api/types'
import type { BenchMotor } from '../bench/benchStore'
import type { PairCheckResult } from './pairCheck'

export interface ThermalSettings {
  load: ThermalLoad
  waveform: ThermalWaveform
  amplitudeMa: number
  offsetMa: number
  frequencyHz: number
  durationMin: number
  loop: boolean
  cooldownMin: number
  tempLimitC: number
  slipDeg: number
  // Spread the pairs' phases evenly so their current peaks take turns.
  stagger: boolean
  // How far a motor is turned when finding or checking a pair.
  pairStepDeg: number
  logCsv: boolean
  logHz: number
  logPartMb: number
}

export interface ThermalMotorSetup {
  included: boolean
}

export interface MotorPair {
  a: number
  b: number
  // The partner's current is inverted so the two push against each other.
  // Face to face on one coupler the same sign already opposes; through a
  // belt or gears it does not — the fixture decides.
  opposed: boolean
  // Last passed coupling check (by hand or by discovery) and the sense it
  // found: +1 partner turns the same way, -1 the opposite way.
  checked?: { at: string; sense: 1 | -1 }
}

export const DEFAULT_SETTINGS: ThermalSettings = {
  load: 'coupled',
  waveform: 'sine',
  amplitudeMa: 150,
  offsetMa: 0,
  frequencyHz: 1,
  durationMin: 10,
  loop: false,
  cooldownMin: 5,
  tempLimitC: 65,
  slipDeg: 45,
  stagger: true,
  pairStepDeg: 15,
  logCsv: true,
  logHz: 10,
  logPartMb: 50,
}

const EMPTY_MOTOR: ThermalMotorSetup = { included: true }

let saveTimer: number | null = null
let saveBody: Partial<ThermalSetupStored> = {}

// Writes are coalesced: a slider drag is one PUT, not fifty.
function save(patch: Partial<ThermalSetupStored>): void {
  saveBody = { ...saveBody, ...patch }
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    const body = saveBody
    saveBody = {}
    saveTimer = null
    api.saveThermalSetup(body).catch(() => undefined)
  }, 300)
}

/** Pairs in number order: (1,2), (3,4), … — the usual way a bench is built. */
export function pairsInOrder(order: BenchMotor[]): MotorPair[] {
  const pairs: MotorPair[] = []
  for (let i = 0; i + 1 < order.length; i += 2) {
    pairs.push({ a: order[i].id, b: order[i + 1].id, opposed: true })
  }
  return pairs
}

export function pairKey(pair: { a: number; b: number }): string {
  return `${pair.a}-${pair.b}`
}

export function partnerOf(pairs: MotorPair[], id: number): MotorPair | null {
  return pairs.find((p) => p.a === id || p.b === id) ?? null
}

interface ThermalState {
  model: string | null
  motorList: BenchMotor[]
  settings: ThermalSettings
  motors: Record<string, ThermalMotorSetup>
  pairs: MotorPair[]
  // Results of the coupling check, by pair; not persisted — a check is for now.
  checks: Record<string, PairCheckResult>
  checking: string | null

  adopt(model: string, motors: BenchMotor[]): void
  // Re-read the backend's copy (after a discovery run wrote it).
  reload(): Promise<void>
  setChecking(key: string | null): void
  setCheck(key: string, result: PairCheckResult | null): void
  patchSettings(patch: Partial<ThermalSettings>): void
  // Including or excluding a motor takes its partner along: the pair is the unit.
  setIncluded(id: number, included: boolean): void
  setAllIncluded(included: boolean): void
  setPairs(pairs: MotorPair[]): void
}

export const useThermalStore = create<ThermalState>((set, get) => ({
  model: null,
  motorList: [],
  settings: DEFAULT_SETTINGS,
  motors: {},
  pairs: [],
  checks: {},
  checking: null,

  setChecking: (checking) => set({ checking }),
  setCheck: (key, result) => {
    const checks = { ...get().checks }
    if (result) checks[key] = result
    else delete checks[key]
    set({ checks })
  },

  adopt: (model, motors) => {
    set({ model, motorList: motors })
    void get().reload()
  },

  reload: async () => {
    const motors = get().motorList
    let stored: ThermalSetupStored = { pairs: null, settings: null, motors: null }
    try {
      stored = await api.thermalSetup()
    } catch {
      /* backend gone: keep what we have */
    }
    const setup: Record<string, ThermalMotorSetup> = {}
    for (const motor of motors) {
      setup[motor.id] = { ...EMPTY_MOTOR, ...(stored.motors?.[motor.id] ?? {}) }
    }
    const ids = new Set(motors.map((m) => m.id))
    // Pairs naming a motor that left the bus are dropped; a bench never
    // paired before starts paired in number order.
    const pairs = (stored.pairs ?? []).filter((p) => ids.has(p.a) && ids.has(p.b) && p.a !== p.b)
    set({
      settings: { ...DEFAULT_SETTINGS, ...((stored.settings ?? {}) as Partial<ThermalSettings>) },
      motors: setup,
      pairs: stored.pairs === null && motors.length > 0 ? pairsInOrder(motors) : pairs,
    })
  },

  patchSettings: (patch) => {
    const next = { ...get().settings, ...patch }
    set({ settings: next })
    save({ settings: next })
  },

  setIncluded: (id, included) => {
    const { motors, pairs } = get()
    const next: Record<string, ThermalMotorSetup> = {
      ...motors,
      [id]: { ...(motors[id] ?? EMPTY_MOTOR), included },
    }
    const pair = partnerOf(pairs, id)
    if (pair) {
      const other = pair.a === id ? pair.b : pair.a
      next[other] = { ...(motors[other] ?? EMPTY_MOTOR), included }
    }
    set({ motors: next })
    save({ motors: next })
  },

  setAllIncluded: (included) => {
    const { motors } = get()
    const next: Record<string, ThermalMotorSetup> = {}
    for (const id of Object.keys(motors)) next[id] = { ...motors[id], included }
    set({ motors: next })
    save({ motors: next })
  },

  setPairs: (pairs) => {
    const { checks } = get()
    // A check belongs to the two motors it was run on.
    const keep = new Set(pairs.map(pairKey))
    set({ pairs, checks: Object.fromEntries(Object.entries(checks).filter(([k]) => keep.has(k))) })
    save({ pairs })
  },
}))

export interface ThermalRunParams {
  motors: { id: number; invert: boolean }[]
  pairs: [number, number][]
  load: ThermalLoad
  waveform: ThermalWaveform
  amplitude_ma: number
  offset_ma: number
  frequency_hz: number
  duration_s: number
  loop: boolean
  cooldown_s: number
  temp_limit_c: number
  slip_deg: number
  stagger: boolean
  log: boolean
  log_hz: number
  log_part_mb: number
}

/** Motors in the test, the partner of an opposed pair inverted. */
export function selectedMotors(
  motors: BenchMotor[],
  setup: Record<string, ThermalMotorSetup>,
  pairs: MotorPair[],
): { id: number; invert: boolean }[] {
  return motors
    .filter((m) => setup[m.id]?.included ?? true)
    .map((m) => {
      const pair = partnerOf(pairs, m.id)
      return { id: m.id, invert: pair !== null && pair.b === m.id && pair.opposed }
    })
}

/** Free motors have no partner: every motor is its own phase slot. */
export function selectedFree(
  motors: BenchMotor[],
  setup: Record<string, ThermalMotorSetup>,
): { id: number; invert: boolean }[] {
  return motors.filter((m) => setup[m.id]?.included ?? true).map((m) => ({ id: m.id, invert: false }))
}

/** Pairs whose motors are both in the test, as the backend takes them. */
export function selectedPairs(
  selected: { id: number }[],
  pairs: MotorPair[],
): [number, number][] {
  const ids = new Set(selected.map((m) => m.id))
  return pairs.filter((p) => ids.has(p.a) && ids.has(p.b)).map((p) => [p.a, p.b])
}

export function runParams(
  motors: { id: number; invert: boolean }[],
  pairs: [number, number][],
  s: ThermalSettings,
): ThermalRunParams {
  return {
    motors,
    pairs: s.load === 'free' ? [] : pairs,
    load: s.load,
    waveform: s.waveform,
    amplitude_ma: s.waveform === 'constant' ? 0 : s.amplitudeMa,
    offset_ma: s.offsetMa,
    frequency_hz: s.frequencyHz,
    duration_s: Math.max(1, Math.round(s.durationMin * 60)),
    loop: s.loop,
    cooldown_s: Math.max(0, Math.round(s.cooldownMin * 60)),
    temp_limit_c: s.tempLimitC,
    slip_deg: s.slipDeg,
    stagger: s.stagger,
    log: s.logCsv,
    log_hz: s.logHz,
    log_part_mb: s.logPartMb,
  }
}

/** Signed current of the waveform at time t (seconds), phase 0. */
export function waveAt(s: ThermalSettings, t: number): number {
  if (s.waveform === 'sine') return s.offsetMa + s.amplitudeMa * Math.sin(2 * Math.PI * s.frequencyHz * t)
  if (s.waveform === 'square') return s.offsetMa + (((t * s.frequencyHz) % 1 + 1) % 1 < 0.5 ? s.amplitudeMa : -s.amplitudeMa)
  return s.offsetMa
}

/** Peak of the supply current Σ|i| over a period for `slots` groups of
 *  `perSlot` motors each, with the phases the backend would assign. */
export function supplyPeakMa(s: ThermalSettings, slots: number, perSlot: number[], stagger: boolean): number {
  if (slots === 0) return 0
  const period = s.waveform === 'constant' ? 1 : 1 / s.frequencyHz
  const span = s.offsetMa === 0 ? period / 2 : period
  let peak = 0
  for (let i = 0; i < 240; i++) {
    const t = (i / 240) * period
    let total = 0
    for (let k = 0; k < slots; k++) {
      const phase = stagger && slots > 1 && s.waveform !== 'constant' ? (k * span) / slots : 0
      total += Math.abs(waveAt(s, t - phase)) * (perSlot[k] ?? 1)
    }
    peak = Math.max(peak, total)
  }
  return peak
}

/** |offset| + amplitude: what the ceiling has to allow. */
export function peakMa(s: ThermalSettings): number {
  return Math.abs(s.offsetMa) + (s.waveform === 'constant' ? 0 : s.amplitudeMa)
}

/** Sixteen distinguishable trace colours; the palette's five are not enough. */
export function traceColor(index: number, count: number, dark: boolean): string {
  const hue = Math.round((index * 360) / Math.max(count, 1) + 200) % 360
  return dark ? `hsl(${hue} 65% 62%)` : `hsl(${hue} 60% 38%)`
}

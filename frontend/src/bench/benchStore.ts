// Bench page state that is the operator's, not the backend's: per motor the
// A/B endpoints and the cycle definition (speed, hold, count, mode, start
// end), plus a set of defaults to stamp onto every motor. Remembered per
// model in localStorage so a bench that was set up yesterday comes back set
// up; the backend only ever sees them as the parameters of a run.

import { create } from 'zustand'
import type { BusScanResult, HandInfo } from '../api/types'

export type CycleMode = 'glide' | 'step'
export type EndName = 'a' | 'b'

export interface CycleSettings {
  speedDegS: number
  holdS: number
  cycles: number
  loop: boolean
  mode: CycleMode
  startAt: EndName
}

export interface MotorSetup extends CycleSettings {
  a: number | null
  b: number | null
  included: boolean
}

export const DEFAULT_SETTINGS: CycleSettings = {
  speedDegS: 180,
  holdS: 0.3,
  cycles: 100,
  loop: false,
  mode: 'glide',
  startAt: 'a',
}

const EMPTY_SETUP: MotorSetup = { ...DEFAULT_SETTINGS, a: null, b: null, included: true }

const KEY = 'orca-ui.bench.v2'

interface Stored {
  motors: Record<string, Partial<MotorSetup>>
  settings: Partial<CycleSettings>
  logCsv: boolean
  logPartMb: number
}

export const DEFAULT_LOG_PART_MB = 50

function load(model: string): Stored {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    const entry = all[model]
    return {
      motors: entry?.motors ?? {},
      settings: entry?.settings ?? {},
      logCsv: entry?.logCsv ?? false,
      logPartMb: entry?.logPartMb ?? DEFAULT_LOG_PART_MB,
    }
  } catch {
    return { motors: {}, settings: {}, logCsv: false, logPartMb: DEFAULT_LOG_PART_MB }
  }
}

function save(
  model: string,
  motors: Record<string, MotorSetup>,
  settings: CycleSettings,
  logCsv: boolean,
  logPartMb: number,
): void {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    all[model] = { motors, settings, logCsv, logPartMb }
    localStorage.setItem(KEY, JSON.stringify(all))
  } catch {
    /* storage disabled: the setup just does not persist */
  }
}

export interface BenchMotor {
  id: number // bus id
  number: number // what the operator calls it ("motor 1")
  joint: string
}

export function motorNumber(joint: string, fallback: number): number {
  const match = /^motor_(\d+)$/.exec(joint)
  return match ? parseInt(match[1], 10) : fallback
}

export function motorLabel(motors: BenchMotor[], id: number | string): string {
  const motor = motors.find((m) => String(m.id) === String(id))
  return motor ? `motor ${motor.number}` : `id ${id}`
}

interface BenchState {
  model: string | null
  motors: BenchMotor[]
  setup: Record<string, MotorSetup>
  // Defaults: what a motor starts with, and what "apply to all" stamps.
  settings: CycleSettings
  // The last bus scan's answer, kept after the operation slot moves on.
  scan: BusScanResult | null
  // Write every sample of a run to CSV under the model's logs/ folder, in
  // numbered parts of at most logPartMb each.
  logCsv: boolean
  logPartMb: number

  adoptHand(info: HandInfo): void
  setLogCsv(on: boolean): void
  setLogPartMb(mb: number): void
  setScan(scan: BusScanResult | null): void
  setEndpoint(id: number, which: EndName, value: number | null): void
  patchMotor(id: number, patch: Partial<MotorSetup>): void
  patchSettings(patch: Partial<CycleSettings>): void
  applyToAll(): void
}

export const useBenchStore = create<BenchState>((set, get) => ({
  model: null,
  motors: [],
  setup: {},
  settings: DEFAULT_SETTINGS,
  scan: null,
  logCsv: false,
  logPartMb: DEFAULT_LOG_PART_MB,

  setScan: (scan) => set({ scan }),

  setLogCsv: (logCsv) => {
    const { model, setup, settings, logPartMb } = get()
    set({ logCsv })
    if (model) save(model, setup, settings, logCsv, logPartMb)
  },

  setLogPartMb: (logPartMb) => {
    const { model, setup, settings, logCsv } = get()
    set({ logPartMb })
    if (model) save(model, setup, settings, logCsv, logPartMb)
  },

  adoptHand: (info) => {
    const motors: BenchMotor[] = info.joints
      .filter((joint) => joint.motor_id !== null)
      .map((joint) => ({
        id: joint.motor_id as number,
        number: motorNumber(joint.id, joint.motor_id as number),
        joint: joint.id,
      }))
      .sort((x, y) => x.number - y.number)
    const same =
      get().model === info.model_name &&
      motors.length === get().motors.length &&
      motors.every(
        (m, i) => m.id === get().motors[i]?.id && m.number === get().motors[i]?.number,
      )
    if (same) return
    const stored = load(info.model_name)
    const settings = { ...DEFAULT_SETTINGS, ...stored.settings }
    const setup: Record<string, MotorSetup> = {}
    for (const motor of motors) {
      setup[motor.id] = {
        ...EMPTY_SETUP,
        ...settings,
        ...(stored.motors[motor.id] ?? {}),
      }
    }
    set({
      model: info.model_name,
      motors,
      setup,
      settings,
      logCsv: stored.logCsv,
      logPartMb: stored.logPartMb,
    })
  },

  setEndpoint: (id, which, value) => get().patchMotor(id, { [which]: value }),

  patchMotor: (id, patch) => {
    const { model, setup, settings, logCsv, logPartMb } = get()
    const next = { ...setup, [id]: { ...(setup[id] ?? EMPTY_SETUP), ...patch } }
    set({ setup: next })
    if (model) save(model, next, settings, logCsv, logPartMb)
  },

  patchSettings: (patch) => {
    const { model, setup, settings, logCsv, logPartMb } = get()
    const next = { ...settings, ...patch }
    set({ settings: next })
    if (model) save(model, setup, next, logCsv, logPartMb)
  },

  applyToAll: () => {
    const { model, setup, settings, motors, logCsv, logPartMb } = get()
    const next: Record<string, MotorSetup> = { ...setup }
    for (const motor of motors) {
      next[motor.id] = { ...(setup[motor.id] ?? EMPTY_SETUP), ...settings }
    }
    set({ setup: next })
    if (model) save(model, next, settings, logCsv, logPartMb)
  },
}))

export interface MotorCycleParams {
  id: number
  from_deg: number
  to_deg: number
  speed_deg_s: number
  hold_s: number
  cycles: number
  loop: boolean
  mode: CycleMode
  start_at: 'from' | 'to'
}

/** Motors with both endpoints set and the include box ticked — what Start sends. */
export function runnableMotors(
  motors: BenchMotor[],
  setups: Record<string, MotorSetup>,
): MotorCycleParams[] {
  return motors
    .map((motor) => ({ motor, setup: setups[motor.id] }))
    .filter(({ setup }) => setup?.included && setup.a !== null && setup.b !== null)
    .map(({ motor, setup }) => ({
      id: motor.id,
      from_deg: setup.a as number,
      to_deg: setup.b as number,
      speed_deg_s: setup.speedDegS,
      hold_s: setup.holdS,
      cycles: setup.cycles,
      loop: setup.loop,
      mode: setup.mode,
      start_at: setup.startAt === 'b' ? 'to' : 'from',
    }))
}

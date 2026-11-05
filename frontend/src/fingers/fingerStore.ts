// Fingers mode state that is the operator's, in the order a hand goes on
// the bench: the tendons and the motor each is wound on; the joints, each a
// combination of tendons with a gain (joint degrees per shaft degree) — the
// coupling; the range of every joint in joint degrees, captured at its open
// and closed ends, and the shaft zeros; and then the joints are what gets
// driven. Kept by the backend beside the bench config (GET/PUT
// /api/fingers/setup), so a hand mounted yesterday comes back mounted on
// any browser.
//
// Slider targets are not persisted: they are the engaged run's, sent as
// fractions (0 open .. 1 closed) and coalesced so a drag is a stream of a
// few posts a second, not one per pixel.

import { create } from 'zustand'
import { api } from '../api/rest'
import type { FingerJointStored, FingerPose, FingerSetupStored, FingerTendon } from '../api/types'
import type { BenchMotor } from '../bench/benchStore'
import { type MotorJoint, couplingProblem, couplingsOf, differentialGains } from './coupling'

export type FingerJoint = FingerJointStored
export type { FingerPose, FingerTendon }

export type FingerStep = 'tendons' | 'coupling' | 'range' | 'control'
export const STEPS: { step: FingerStep; label: string; title: string }[] = [
  { step: 'tendons', label: '1 · Tendons', title: 'which motor each tendon is wound on' },
  { step: 'coupling', label: '2 · Coupling', title: 'which tendons move each joint, and by how much' },
  { step: 'range', label: '3 · Range', title: 'the open and the closed end of every joint' },
  { step: 'control', label: '4 · Control', title: 'drive the joints' },
]
const STEP_KEY = 'orca-ui.bench.fingers.step'

export interface FingerSettings {
  speedDegS: number
  // Tendon routing of every finger: MCP and PIP read as a sum and a
  // difference of two shafts (q = r_s (θ_U ± θ_C) / r), abduction on its own.
  spoolRadiusMm: number
  mcpRadiusMm: number
  pipRadiusMm: number
  // Cycling through the poses: rounds (0: until stopped) and the hold at each.
  cycleCount: number
  cycleDwellS: number
}

export const DEFAULT_SETTINGS: FingerSettings = {
  speedDegS: 180,
  spoolRadiusMm: 10,
  mcpRadiusMm: 19.6,
  pipRadiusMm: 16.6,
  cycleCount: 10,
  cycleDwellS: 0.5,
}
export const NAME_RE = /^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,31}$/

// A hand's tendons and joints by finger: the template a full hand starts
// from. In every finger MCP and PIP are coupled on two flexion tendons,
// numbered from the thumb side: 1 is the one nearer the thumb (U in the
// formula), 2 the other (C); abduction, the thumb's DIP and the two wrist
// axes are a tendon each.
const FINGERS = ['index', 'middle', 'ring', 'pinky']
export const HAND_TENDONS: string[] = [
  'thumb_abd', 'thumb_1', 'thumb_2', 'thumb_dip',
  ...FINGERS.flatMap((f) => [`${f}_abd`, `${f}_1`, `${f}_2`]),
  'wrist_flex', 'wrist_abd',
]
export const HAND_JOINTS: { name: string; group: string; tendons: string[] }[] = [
  { name: 'thumb_abd', group: 'thumb', tendons: ['thumb_abd'] },
  { name: 'thumb_mcp', group: 'thumb', tendons: ['thumb_1', 'thumb_2'] },
  { name: 'thumb_pip', group: 'thumb', tendons: ['thumb_1', 'thumb_2'] },
  { name: 'thumb_dip', group: 'thumb', tendons: ['thumb_dip'] },
  ...FINGERS.flatMap((f) => [
    { name: `${f}_abd`, group: f, tendons: [`${f}_abd`] },
    { name: `${f}_mcp`, group: f, tendons: [`${f}_1`, `${f}_2`] },
    { name: `${f}_pip`, group: f, tendons: [`${f}_1`, `${f}_2`] },
  ]),
  { name: 'wrist_flex', group: 'wrist', tendons: ['wrist_flex'] },
  { name: 'wrist_abd', group: 'wrist', tendons: ['wrist_abd'] },
]

const SEND_INTERVAL_MS = 50

let saveTimer: number | null = null
let saveBody: Partial<FingerSetupStored> = {}

function save(patch: Partial<FingerSetupStored>): void {
  saveBody = { ...saveBody, ...patch }
  if (saveTimer !== null) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    const body = saveBody
    saveBody = {}
    saveTimer = null
    api.saveFingerSetup(body).catch(() => undefined)
  }, 300)
}

let sendTimer: number | null = null
let sendBody: Record<string, number> = {}

function send(targets: Record<string, number>): void {
  sendBody = { ...sendBody, ...targets }
  if (sendTimer !== null) return
  sendTimer = window.setTimeout(() => {
    const body = sendBody
    sendBody = {}
    sendTimer = null
    api.fingerTargets(body).catch(() => undefined)
  }, SEND_INTERVAL_MS)
}

/** The tendons a joint's dropdown offers: those of its own finger (named
 *  `<finger>_…`), plus whatever it already names; every tendon when the
 *  finger has none of its own. */
export function tendonsFor(joint: FingerJoint, tendons: FingerTendon[]): FingerTendon[] {
  const prefix = joint.group ? `${joint.group.toLowerCase()}_` : ''
  const own = prefix ? tendons.filter((t) => t.name.toLowerCase().startsWith(prefix)) : []
  if (own.length === 0) return tendons
  const named = new Set(joint.terms.map((t) => t.tendon))
  return tendons.filter((t) => own.includes(t) || named.has(t.name))
}

/** Joints with their tendon terms turned into motor terms. */
export function resolve(joints: FingerJoint[], tendons: FingerTendon[]): MotorJoint[] {
  const tendonOf = new Map(tendons.map((t) => [t.name, t]))
  return joints.map((joint) => {
    const terms: MotorJoint['terms'] = []
    const unresolved: string[] = []
    for (const term of joint.terms) {
      const tendon = term.tendon !== undefined ? tendonOf.get(term.tendon) : undefined
      const motor = term.tendon !== undefined ? tendon?.motor : term.motor
      if (motor === null || motor === undefined) unresolved.push(term.tendon ?? '?')
      else terms.push({ motor, gain: term.gain * (tendon?.direction ?? 1) })
    }
    return {
      name: joint.name,
      group: joint.group,
      open_deg: joint.open_deg,
      closed_deg: joint.closed_deg,
      terms,
      unresolved,
    }
  })
}

/** A joint with both ends captured and apart; whether its coupling can be
 *  driven is the coupling's question (see `readyJoints`). */
export function hasRange(joint: { open_deg: number | null; closed_deg: number | null }): boolean {
  return (
    joint.open_deg !== null && joint.closed_deg !== null && Math.abs(joint.closed_deg - joint.open_deg) >= 1
  )
}

/** The joints Engage sends: every joint of every coupling that is complete
 *  and solvable. A coupling with one unfinished joint is left out whole —
 *  its motors cannot be driven for the others alone. */
export function readyJoints(resolved: MotorJoint[]): MotorJoint[] {
  return couplingsOf(resolved)
    .filter((c) => couplingProblem(c) === null && c.joints.every(hasRange))
    .flatMap((c) => c.joints)
}

export function fractionOf(
  joint: { open_deg: number | null; closed_deg: number | null },
  deg: number,
): number | null {
  if (joint.open_deg === null || joint.closed_deg === null) return null
  const span = joint.closed_deg - joint.open_deg
  if (Math.abs(span) < 1e-6) return null
  return Math.min(1, Math.max(0, (deg - joint.open_deg) / span))
}

/** Joints in their groups, in first-seen order; ungrouped joints last. */
export function groupsOf<J extends { group: string }>(joints: J[]): { group: string; joints: J[] }[] {
  const order: string[] = []
  const by = new Map<string, J[]>()
  for (const joint of joints) {
    const key = joint.group || ''
    if (!by.has(key)) {
      by.set(key, [])
      order.push(key)
    }
    by.get(key)!.push(joint)
  }
  return order
    .sort((a, b) => (a === '' ? 1 : b === '' ? -1 : 0))
    .map((group) => ({ group, joints: by.get(group)! }))
}

function uniqueName(taken: string[], base: string): string {
  const set = new Set(taken.map((n) => n.toLowerCase()))
  if (!set.has(base.toLowerCase())) return base
  for (let i = 2; ; i++) {
    const candidate = `${base}_${i}`
    if (!set.has(candidate.toLowerCase())) return candidate
  }
}

interface FingerState {
  model: string | null
  motorList: BenchMotor[]
  step: FingerStep
  tendons: FingerTendon[]
  joints: FingerJoint[]
  zeros: Record<string, number>
  settings: FingerSettings
  // Slider positions while engaged, by joint name.
  targets: Record<string, number>
  // Named poses: slider positions kept with the setup.
  poses: FingerPose[]

  setStep(step: FingerStep): void
  adopt(model: string, motors: BenchMotor[]): void
  reload(): Promise<void>
  patchSettings(patch: Partial<FingerSettings>): void

  addTendon(): void
  removeTendon(index: number): void
  // Renaming a tendon renames it in every joint's terms.
  patchTendon(index: number, patch: Partial<FingerTendon>): void
  setTendons(tendons: FingerTendon[]): void

  addJoint(): void
  removeJoint(index: number): void
  patchJoint(index: number, patch: Partial<FingerJoint>): void
  setJoints(joints: FingerJoint[]): void
  moveJoint(index: number, direction: 1 | -1): void
  // A whole hand: its tendons on the motors by number, its joints, MCP and
  // PIP of each finger coupled from the radii; replaces both lists.
  addHand(): void
  // Re-derive every finger's MCP/PIP gains from the radii on the tendons
  // those rows name (the first two distinct ones are tendon 1 U and 2 C).
  coupleFingers(): void
  setZeros(zeros: Record<string, number>): void

  presets: { name: string; saved_at: number }[]
  loadPresets(): Promise<void>
  savePreset(name: string): Promise<void>
  loadPreset(name: string): Promise<void>
  deletePreset(name: string): Promise<void>

  // Seed the sliders from the run (on engage, or opening the page mid-run).
  seedTargets(targets: Record<string, number>): void
  setTarget(name: string, fraction: number): void
  setTargets(targets: Record<string, number>): void

  // Keep the sliders as a named pose; an existing name is overwritten.
  capturePose(name: string, targets: Record<string, number>): void
  removePose(index: number): void
  movePose(index: number, by: -1 | 1): void
}

export const useFingerStore = create<FingerState>((set, get) => ({
  model: null,
  motorList: [],
  step: (() => {
    try {
      const stored = localStorage.getItem(STEP_KEY)
      return STEPS.some((s) => s.step === stored) ? (stored as FingerStep) : 'tendons'
    } catch {
      return 'tendons'
    }
  })(),
  tendons: [],
  joints: [],
  zeros: {},
  settings: DEFAULT_SETTINGS,
  targets: {},
  poses: [],

  setStep: (step) => {
    set({ step })
    try {
      localStorage.setItem(STEP_KEY, step)
    } catch {
      /* storage disabled: the step just does not persist */
    }
  },

  adopt: (model, motors) => {
    set({ model, motorList: motors })
    void get().reload()
    void get().loadPresets()
  },

  presets: [],
  loadPresets: async () => {
    try {
      set({ presets: (await api.fingerPresets()).presets })
    } catch {
      /* backend gone */
    }
  },
  savePreset: async (name) => {
    // The autosave is coalesced: flush it so the preset is what is on screen.
    if (saveTimer !== null) {
      window.clearTimeout(saveTimer)
      saveTimer = null
      const body = saveBody
      saveBody = {}
      await api.saveFingerSetup(body)
    }
    set({ presets: (await api.saveFingerPreset(name)).presets })
  },
  loadPreset: async (name) => {
    await api.loadFingerPreset(name)
    await get().reload()
  },
  deletePreset: async (name) => {
    set({ presets: (await api.deleteFingerPreset(name)).presets })
  },

  reload: async () => {
    let stored: FingerSetupStored = { tendons: null, joints: null, zeros: null, settings: null, poses: null }
    try {
      stored = await api.fingerSetup()
    } catch {
      /* backend gone: keep what we have */
    }
    set({
      tendons: stored.tendons ?? [],
      joints: (stored.joints ?? []).map((j) => ({ ...j, terms: j.terms ?? [] })),
      zeros: stored.zeros ?? {},
      settings: { ...DEFAULT_SETTINGS, ...((stored.settings ?? {}) as Partial<FingerSettings>) },
      poses: stored.poses ?? [],
    })
  },

  patchSettings: (patch) => {
    const next = { ...get().settings, ...patch }
    set({ settings: next })
    save({ settings: next })
  },

  // ----- tendons -----------------------------------------------------------

  addTendon: () => {
    const { tendons, motorList } = get()
    const used = new Set(tendons.map((t) => t.motor))
    const free = motorList.find((m) => !used.has(m.id))
    get().setTendons([
      ...tendons,
      { name: uniqueName(tendons.map((t) => t.name), 'tendon'), motor: free ? free.id : null },
    ])
  },

  removeTendon: (index) => get().setTendons(get().tendons.filter((_, i) => i !== index)),

  patchTendon: (index, patch) => {
    const { tendons, joints } = get()
    const tendon = tendons[index]
    if (!tendon) return
    const next = tendons.map((t, i) => (i === index ? { ...t, ...patch } : t))
    if (patch.name !== undefined) {
      const clash = next.some((t, i) => i !== index && t.name.toLowerCase() === patch.name!.toLowerCase())
      if (clash || !NAME_RE.test(patch.name)) {
        set({ tendons: next })
        return
      }
      get().setJoints(
        joints.map((j) => ({
          ...j,
          terms: j.terms.map((t) => (t.tendon === tendon.name ? { ...t, tendon: patch.name! } : t)),
        })),
      )
    }
    if (patch.motor !== undefined && patch.motor !== null) {
      // A motor winds one tendon: taking it frees the other tendon.
      for (let i = 0; i < next.length; i++) {
        if (i !== index && next[i].motor === patch.motor) next[i] = { ...next[i], motor: null }
      }
    }
    get().setTendons(next)
  },

  setTendons: (tendons) => {
    set({ tendons })
    save({ tendons })
  },

  // ----- joints ------------------------------------------------------------

  addJoint: () => {
    const { joints, tendons } = get()
    const used = new Set(joints.flatMap((j) => j.terms.map((t) => t.tendon)))
    const free = tendons.find((t) => !used.has(t.name))
    get().setJoints([
      ...joints,
      {
        name: uniqueName(joints.map((j) => j.name), 'joint'),
        terms: free ? [{ tendon: free.name, gain: 1 }] : [],
        open_deg: null,
        closed_deg: null,
        group: joints.length > 0 ? joints[joints.length - 1].group : '',
      },
    ])
  },

  removeJoint: (index) => get().setJoints(get().joints.filter((_, i) => i !== index)),

  patchJoint: (index, patch) => {
    const joints = get().joints
    if (!joints[index]) return
    const next = joints.map((j, i) => (i === index ? { ...j, ...patch } : j))
    // The file refuses duplicate names; the page keeps them unique as typed,
    // showing the draft without saving it.
    if (patch.name !== undefined) {
      const clash = next.some((j, i) => i !== index && j.name.toLowerCase() === patch.name!.toLowerCase())
      if (clash || !NAME_RE.test(patch.name)) {
        set({ joints: next })
        return
      }
    }
    get().setJoints(next)
  },

  setJoints: (joints) => {
    set({ joints })
    save({ joints })
  },

  moveJoint: (index, direction) => {
    const joints = [...get().joints]
    const other = index + direction
    if (!joints[index] || !joints[other]) return
    ;[joints[index], joints[other]] = [joints[other], joints[index]]
    get().setJoints(joints)
  },

  addHand: () => {
    const motors = [...get().motorList].sort((x, y) => x.number - y.number)
    get().setTendons(HAND_TENDONS.map((name, i) => ({ name, motor: motors[i]?.id ?? null })))
    set({
      joints: HAND_JOINTS.map((j) => ({
        name: j.name,
        group: j.group,
        terms: j.tendons.map((tendon) => ({ tendon, gain: 1 })),
        open_deg: null,
        closed_deg: null,
      })),
    })
    get().coupleFingers()
  },

  coupleFingers: () => {
    const { joints, settings } = get()
    const gains = differentialGains(settings.spoolRadiusMm, settings.mcpRadiusMm, settings.pipRadiusMm)
    const next = [...joints]
    for (const { joints: members } of groupsOf(joints)) {
      const mcp = members.find((j) => /_mcp$/i.test(j.name))
      const pip = members.find((j) => /_pip$/i.test(j.name))
      if (!mcp || !pip) continue
      const names = [...new Set([...mcp.terms, ...pip.terms].map((t) => t.tendon).filter((t) => t))] as string[]
      const [u, c] = names
      if (!u || !c) continue
      next[joints.indexOf(mcp)] = {
        ...mcp,
        terms: [{ tendon: u, gain: gains.mcp }, { tendon: c, gain: gains.mcp }],
      }
      next[joints.indexOf(pip)] = {
        ...pip,
        terms: [{ tendon: u, gain: gains.pip }, { tendon: c, gain: -gains.pip }],
      }
    }
    get().setJoints(next)
  },

  setZeros: (zeros) => {
    set({ zeros })
    save({ zeros })
  },

  // ----- targets -----------------------------------------------------------

  seedTargets: (targets) => set({ targets }),

  setTarget: (name, fraction) => get().setTargets({ [name]: fraction }),

  setTargets: (targets) => {
    const clean: Record<string, number> = {}
    for (const [name, value] of Object.entries(targets)) clean[name] = Math.min(1, Math.max(0, value))
    set({ targets: { ...get().targets, ...clean } })
    send(clean)
  },

  // ----- poses -------------------------------------------------------------

  capturePose: (name, targets) => {
    const pose = { name, targets: { ...targets } }
    const poses = get().poses
    const at = poses.findIndex((p) => p.name.toLowerCase() === name.toLowerCase())
    const next = at < 0 ? [...poses, pose] : poses.map((p, i) => (i === at ? pose : p))
    set({ poses: next })
    save({ poses: next })
  },
  removePose: (index) => {
    const next = get().poses.filter((_, i) => i !== index)
    set({ poses: next })
    save({ poses: next })
  },
  movePose: (index, by) => {
    const next = [...get().poses]
    const to = index + by
    if (to < 0 || to >= next.length) return
    ;[next[index], next[to]] = [next[to], next[index]]
    set({ poses: next })
    save({ poses: next })
  },
}))

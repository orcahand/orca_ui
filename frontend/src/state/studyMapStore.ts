// The visual calibration study's joint map (orca_ui/hand/study_map.py): which map, if any, is
// the hand's joint mapping for all of orca-ui (every target out, every estimate in), and the
// per-joint tables to show what the hand really does.

import { create } from 'zustand'

export interface StudyJoint {
  applied: boolean
  confidence: 'good' | 'fair' | 'low'
  noise_deg: number | null
  cmd_knots: number[]
  cmd_true: number[]
  assumed_knots: number[]
  assumed_true: number[]
  reach: [number, number]
  rom: [number, number]
  gain: number
  offset_at_0: number
}

export interface StudyAccuracy {
  rms: number
  p50: number
  p95: number
  max: number
  n: number
}

export interface StudyMapOption {
  name: string
  label: string
  /** What the model is, e.g. "monotone curve per joint". */
  approach: string
  created: string | null
  n_poses: number | null
  params: number | null
  heldout: StudyAccuracy | null
  heldout_standard: StudyAccuracy | null
}

/** One ghost-hand overlay row (orca_ui/hand/overlays.py): a joint mapping drawn beside the hand. */
export interface OverlayRow {
  id: string
  kind: 'basic' | 'main' | 'fitted' | 'other-hand'
  label: string
  approach: string
  heldout?: StudyAccuracy | null
  params?: number | null
  n_poses?: number | null
  created?: string | null
  /** The study-map mode that drives the hand with this mapping ("off" = orca_core basic). */
  mode?: string
}

export interface OverlaySetting {
  visible: boolean
  /** null: the automatic colour. */
  color: string | null
  opacity: number
}

export interface StudyMapState {
  enabled: boolean
  /** "off" or the name of one of `options` (the connected hand's maps). */
  mode: string
  hand: string | null
  available: boolean
  options: StudyMapOption[]
  /** The "off" choice: orca_core's own map. */
  standard: { label: string; approach: string }
  /** What a selected map applies to. */
  scope: string
  overlays?: OverlayRow[]
  map: {
    created: string
    n_poses: number
    hysteresis: string
    kind?: string
    coupled?: unknown
    advanced?: unknown
    joints: Record<string, StudyJoint>
  } | null
}

const BASE = '/api/visual-calibration/study-map'
const OVERLAY_KEY = 'orca.studyMap.overlays'
const OLD_OPACITY_KEY = 'orca.studyMap.standardOpacity'

// Distinct hues that read on both the dark viewport and paper; main keeps the red it always had.
export const OVERLAY_COLORS = [
  '#dc2626', '#2563eb', '#16a34a', '#d97706', '#9333ea', '#0891b2',
  '#db2777', '#65a30d', '#ea580c', '#4f46e5', '#0d9488', '#a16207',
]

export function autoColor(rows: OverlayRow[], id: string): string {
  if (id === 'main') return OVERLAY_COLORS[0]
  const i = rows.filter((r) => r.id !== 'main').findIndex((r) => r.id === id)
  return OVERLAY_COLORS[1 + (Math.max(i, 0) % (OVERLAY_COLORS.length - 1))]
}

function oldMainOpacity(): number {
  try {
    const v = parseFloat(localStorage.getItem(OLD_OPACITY_KEY) ?? '')
    return isFinite(v) ? Math.min(Math.max(v, 0), 1) : 0.35
  } catch {
    return 0.35
  }
}

const MAIN_OPACITY = oldMainOpacity()

function defaultSetting(id: string): OverlaySetting {
  if (id !== 'main') return { visible: false, color: null, opacity: 0.35 }
  return { visible: MAIN_OPACITY > 0, color: null, opacity: MAIN_OPACITY || 0.35 }
}

function storedSettings(): Record<string, Partial<OverlaySetting>> {
  try {
    const v = JSON.parse(localStorage.getItem(OVERLAY_KEY) ?? '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}

interface Store {
  state: StudyMapState | null
  /** Per overlay id; rows never touched fall back to defaultSetting. */
  overlaySettings: Record<string, Partial<OverlaySetting>>
  error: string | null
  load(): Promise<void>
  setEnabled(on: boolean): Promise<void>
  setMode(mode: string): Promise<void>
  setOverlay(id: string, patch: Partial<OverlaySetting>): void
  setAllOverlays(visible: boolean): void
}

export function overlaySetting(id: string, settings = useStudyMap.getState().overlaySettings): OverlaySetting {
  return { ...defaultSetting(id), ...settings[id] }
}

function persist(settings: Record<string, Partial<OverlaySetting>>) {
  try {
    localStorage.setItem(OVERLAY_KEY, JSON.stringify(settings))
  } catch {
    /* private window or blocked storage: keep it for this session only */
  }
}

export const useStudyMap = create<Store>((set, get) => ({
  state: null,
  overlaySettings: storedSettings(),
  error: null,
  async load() {
    try {
      const r = await fetch(BASE)
      if (r.ok) set({ state: await r.json(), error: null })
    } catch (e) {
      set({ error: String(e) })
    }
  },
  async setEnabled(on) {
    const r = await fetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: on }),
    })
    if (r.ok) set({ state: await r.json(), error: null })
    else set({ error: (await r.json().catch(() => ({}))).detail ?? r.statusText })
  },
  async setMode(mode) {
    const r = await fetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
    if (r.ok) set({ state: await r.json(), error: null })
    else set({ error: (await r.json().catch(() => ({}))).detail ?? r.statusText })
  },
  setOverlay(id, patch) {
    const all = get().overlaySettings
    const next = { ...all, [id]: { ...all[id], ...patch } }
    persist(next)
    set({ overlaySettings: next })
  },
  setAllOverlays(visible) {
    const next = { ...get().overlaySettings }
    for (const r of get().state?.overlays ?? []) next[r.id] = { ...next[r.id], visible }
    persist(next)
    set({ overlaySettings: next })
  },
}))

function interp(x: number, xs: number[], ys: number[]): number {
  if (x <= xs[0]) return ys[0]
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1]
  let i = 1
  while (xs[i] < x) i++
  const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
  return ys[i - 1] + t * (ys[i] - ys[i - 1])
}

/** Where each joint really is according to the study, from orca_core's motor estimate. */
export function correctedPose(estimate: Record<string, number>): Record<string, number> {
  const joints = useStudyMap.getState().state?.map?.joints
  if (!joints) return estimate
  const out: Record<string, number> = {}
  for (const [j, v] of Object.entries(estimate)) {
    const t = joints[j]
    out[j] = t && v != null ? interp(v, t.assumed_knots, t.assumed_true) : v
  }
  return out
}

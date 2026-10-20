// Which tensioning dialog a hand gets, and the dialogs' open/dismissed state.
// v2.1 hands get guided tensioning (scored against the travel baseline);
// v2.0 and unknown hands get the hold dialog: activate the current, ratchet.
// The operator can force either one; the choice is remembered per browser.
// The dialogs are mounted once (TensionDialogs), so any flow that tensions
// gets the same UI for the same hand.

import { create } from 'zustand'
import { useAppStore } from './appStore'

export type TensionMode = 'guided' | 'hold'

export const V21 = 21
const FORCED_KEY = 'orca.tension.forcedMode'
const OFFSET_KEY = 'orca.tension.offsetDeg'
// How far the finger motors slowly turn counterclockwise while you ratchet, and what one
// "Pull more" adds. Mirror the backend's tension.py.
// 0 holds the motors still while ratcheting, as tensioning did before the guided
// rework. A pull leaves a standing position error that saturates the goal current,
// taking away the headroom a motor needs to resist the ratchet.
export const DEFAULT_OFFSET_DEG = 0
export const EXTRA_DEG = 15
export const PULL_MORE = 'Pull more'
export const OFFSET_BOUNDS_DEG = [0, 45] as const

export function formatHardwareVersion(version: number | null | undefined): string {
  if (version == null) return '?'
  const [major, minor] = version < 10 ? [version, 0] : [Math.floor(version / 10), version % 10]
  return `v${major}.${minor}`
}

function loadForced(): TensionMode | null {
  try {
    const value = localStorage.getItem(FORCED_KEY)
    return value === 'guided' || value === 'hold' ? value : null
  } catch {
    return null
  }
}

function loadOffset(): number {
  try {
    const value = Number(localStorage.getItem(OFFSET_KEY) ?? NaN)
    if (Number.isFinite(value) && value >= OFFSET_BOUNDS_DEG[0] && value <= OFFSET_BOUNDS_DEG[1]) {
      return value
    }
  } catch {
    /* storage unavailable */
  }
  return DEFAULT_OFFSET_DEG
}

interface TensionFlowState {
  forced: TensionMode | null
  setForced: (mode: TensionMode | null) => void
  // Hold dialog opened by the operator, before any operation exists.
  holdOpen: boolean
  openHold: () => void
  closeHold: () => void
  offsetDeg: number
  setOffsetDeg: (offsetDeg: number) => void
  // Wind the tendons to the hard stops before the hold.
  wind: boolean
  setWind: (wind: boolean) => void
  // The run whose dialog the operator closed; a later run shows again.
  dismissed: string | null
  dismiss: (runId: string | null) => void
}

export const useTensionFlow = create<TensionFlowState>((set) => ({
  forced: loadForced(),
  setForced: (forced) => {
    try {
      if (forced) localStorage.setItem(FORCED_KEY, forced)
      else localStorage.removeItem(FORCED_KEY)
    } catch {
      /* storage unavailable: the choice lasts this page load */
    }
    set({ forced })
  },
  offsetDeg: loadOffset(),
  setOffsetDeg: (offsetDeg) => {
    try {
      localStorage.setItem(OFFSET_KEY, String(offsetDeg))
    } catch {
      /* storage unavailable: the value lasts this page load */
    }
    set({ offsetDeg })
  },
  holdOpen: false,
  openHold: () => set({ holdOpen: true }),
  closeHold: () => set({ holdOpen: false }),
  wind: false,
  setWind: (wind) => set({ wind }),
  dismissed: null,
  dismiss: (dismissed) => set({ dismissed }),
}))

export function useTensionMode(): {
  mode: TensionMode
  natural: TensionMode
  forced: TensionMode | null
  isV21: boolean
} {
  const version = useAppStore((s) => s.status?.hardware_version ?? null)
  const forced = useTensionFlow((s) => s.forced)
  const isV21 = version === V21
  const natural: TensionMode = isV21 ? 'guided' : 'hold'
  return { mode: forced ?? natural, natural, forced, isV21 }
}

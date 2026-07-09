// Control-plane state (human-speed changes -> normal React renders).
// Hot loops read via useAppStore.getState() without subscribing.

import { create } from 'zustand'
import type {
  ControlState,
  HandInfo,
  StatusSnapshot,
  TactileMode,
} from '../api/types'

export type TaxelDisplayMode = 'magnitude' | 'direction' | 'arrows'
export type ArrowColorScheme = 'heat' | 'intensity' | 'orca'
export type ViewName =
  | 'dashboard'
  | '3d'
  | 'poses'
  | 'teleop'
  | 'setup'
  | 'motors'

export interface TactileSettings {
  displayMode: TaxelDisplayMode
  colorScheme: ArrowColorScheme
  thresholdEnabled: boolean
  threshold: number
  lengthMult: number
  thicknessMult: number
}

export interface SceneSettings {
  ghost: boolean
  forceResultant: boolean
  forceTaxels: boolean
  jointGlow: boolean
  // Accent-colored ghost posed from the live teleop retargeter output.
  teleopGhost: boolean
}

interface AppState {
  wsConnected: boolean
  status: StatusSnapshot | null
  handInfo: HandInfo | null
  control: ControlState | null
  view: ViewName
  tactile: TactileSettings
  scene: SceneSettings
  showSparklineTarget: boolean
  rates: Record<string, number>
  error: string | null

  setWsConnected(up: boolean): void
  setStatus(status: StatusSnapshot): void
  setHandInfo(info: HandInfo): void
  setControl(control: ControlState): void
  setView(view: ViewName): void
  setTactile(patch: Partial<TactileSettings>): void
  setScene(patch: Partial<SceneSettings>): void
  setShowSparklineTarget(show: boolean): void
  setRates(rates: Record<string, number>): void
  setError(error: string | null): void
  setTactileMode(mode: TactileMode): void
}

const SCENE_DEFAULTS: SceneSettings = {
  ghost: false,
  forceResultant: false,
  forceTaxels: false,
  jointGlow: false,
  teleopGhost: true,
}

const storedScene = ((): SceneSettings => {
  try {
    return {
      ...SCENE_DEFAULTS,
      ...JSON.parse(localStorage.getItem('orca-ui.scene') ?? '{}'),
    }
  } catch {
    return { ...SCENE_DEFAULTS }
  }
})()

export const useAppStore = create<AppState>((set) => ({
  wsConnected: false,
  status: null,
  handInfo: null,
  control: null,
  view: 'dashboard',
  tactile: {
    displayMode: 'magnitude',
    colorScheme: 'heat',
    thresholdEnabled: false,
    threshold: 0,
    lengthMult: 0.5,
    thicknessMult: 0.5,
  },
  scene: storedScene,
  showSparklineTarget:
    localStorage.getItem('orca-ui.sparkline-target') === 'true',
  rates: {},
  error: null,

  setWsConnected: (up) => set({ wsConnected: up }),
  setStatus: (status) => set({ status }),
  setHandInfo: (info) => set({ handInfo: info, control: info.control }),
  setControl: (control) => set({ control }),
  setView: (view) => set({ view }),
  setTactile: (patch) =>
    set((state) => ({ tactile: { ...state.tactile, ...patch } })),
  setScene: (patch) =>
    set((state) => {
      const scene = { ...state.scene, ...patch }
      localStorage.setItem('orca-ui.scene', JSON.stringify(scene))
      return { scene }
    }),
  setShowSparklineTarget: (show) => {
    localStorage.setItem('orca-ui.sparkline-target', String(show))
    set({ showSparklineTarget: show })
  },
  setRates: (rates) => set({ rates }),
  setError: (error) => set({ error }),
  setTactileMode: (mode) =>
    set((state) => ({
      control: state.control ? { ...state.control, tactile_mode: mode } : null,
    })),
}))

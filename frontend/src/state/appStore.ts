// Control-plane state (human-speed changes -> normal React renders).
// Hot loops read via useAppStore.getState() without subscribing.

import { create } from 'zustand'
import type {
  ControlState,
  Finger,
  HandInfo,
  StatusSnapshot,
  TactileMode,
} from '../api/types'

export type TaxelDisplayMode = 'magnitude' | 'direction' | 'arrows'
export type ArrowColorScheme = 'heat' | 'intensity' | 'orca'
export type FunSoundMode =
  | 'off'
  | 'soundtrack'
  | 'cow'
  | 'engine'
  | 'squeak'
  | 'theremin'
export type MusicScale =
  | 'chromatic'
  | 'major'
  | 'minor'
  | 'pentMajor'
  | 'pentMinor'
  | 'majorChord'
  | 'minorChord'
export type ViewName =
  | 'dashboard'
  | 'poses'
  | 'teleop'
  | 'setup'
  | 'motors'
  | 'stats'

export interface TactileSettings {
  displayMode: TaxelDisplayMode
  colorScheme: ArrowColorScheme
  thresholdEnabled: boolean
  threshold: number
  lengthMult: number
  thicknessMult: number
  funEnabled: boolean
  funSounds: Record<Finger, FunSoundMode>
  // Dynamic range: force (N) where a sound engages / reaches full effect.
  // Shared by fun mode and music mode.
  funOnN: number
  funFullN: number
  musicEnabled: boolean
  musicVol: number
  // Harmony: only notes of this scale (root 0 = C ... 11 = B) are playable.
  musicRoot: number
  musicScale: MusicScale
}

export interface SceneSettings {
  ghost: boolean
  forceResultant: boolean
  forceTaxels: boolean
  jointGlow: boolean
  // Accent-colored ghost posed from the live teleop retargeter output.
  teleopGhost: boolean
  // Freeze the camera: orbit/pan/zoom are ignored until unlocked.
  lockView: boolean
}

interface AppState {
  wsConnected: boolean
  status: StatusSnapshot | null
  handInfo: HandInfo | null
  control: ControlState | null
  view: ViewName
  tactile: TactileSettings
  scene: SceneSettings
  // Manual joint-sensor calibration mode: sliders pose ONLY the 3D model
  // (no motor commands — the physical hand is posed by hand, torque off)
  // and each encoder-backed slider grows a Calibrate button.
  manualCal: boolean
  manualCalPose: Record<string, number>
  showSparklineTarget: boolean
  rates: Record<string, number>
  error: string | null

  setWsConnected(up: boolean): void
  setStatus(status: StatusSnapshot): void
  setHandInfo(info: HandInfo): void
  setControl(control: ControlState): void
  setView(view: ViewName): void
  setManualCal(on: boolean): void
  setManualCalPose(joint: string, deg: number): void
  setTactile(patch: Partial<TactileSettings>): void
  setScene(patch: Partial<SceneSettings>): void
  setShowSparklineTarget(show: boolean): void
  setRates(rates: Record<string, number>): void
  setError(error: string | null): void
  setTactileMode(mode: TactileMode): void
}

const SCENE_DEFAULTS: SceneSettings = {
  ghost: false,
  forceResultant: true,
  forceTaxels: true,
  jointGlow: false,
  teleopGhost: true,
  lockView: false,
}

// Bumped when a default changes: stored settings win over defaults, so a new
// default would never reach anyone who has opened the 3D tab before. The key
// change drops the old blob once and everything returns to the defaults above.
const SCENE_KEY = 'orca-ui.scene.v2'

const storedScene = ((): SceneSettings => {
  try {
    return {
      ...SCENE_DEFAULTS,
      ...JSON.parse(localStorage.getItem(SCENE_KEY) ?? '{}'),
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
  manualCal: false,
  manualCalPose: {},
  tactile: {
    displayMode: 'magnitude',
    colorScheme: 'heat',
    thresholdEnabled: false,
    threshold: 0,
    lengthMult: 0.5,
    thicknessMult: 0.5,
    funEnabled: false,
    funSounds: {
      thumb: 'engine',
      index: 'soundtrack',
      middle: 'cow',
      ring: 'squeak',
      pinky: 'theremin',
    },
    funOnN: 1,
    funFullN: 12,
    musicEnabled: false,
    musicVol: 0.5,
    musicRoot: 0,
    musicScale: 'major',
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
  setManualCal: (on) => set({ manualCal: on, manualCalPose: {} }),
  setManualCalPose: (joint, deg) =>
    set((state) => ({
      manualCalPose: { ...state.manualCalPose, [joint]: deg },
    })),
  setTactile: (patch) =>
    set((state) => ({ tactile: { ...state.tactile, ...patch } })),
  setScene: (patch) =>
    set((state) => {
      const scene = { ...state.scene, ...patch }
      localStorage.setItem(SCENE_KEY, JSON.stringify(scene))
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

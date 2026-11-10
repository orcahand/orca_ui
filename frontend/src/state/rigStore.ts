// The calibration rig on the dashboard (docs/rig-dashboard.md): whether orca-ui found it,
// and while it is connected the twin's live pose (plate angle, hand on the plate).
// Polled only while a view uses it (useRigPolling); an older server without the rig
// API simply reads as "no rig".

import { useEffect } from 'react'
import { create } from 'zustand'
import {
  visualApi,
  type RigInfo,
  type RigPresence,
  type TwinInfo,
  type TwinState,
} from '../components/visual/api'

interface RigStore {
  presence: RigPresence | null
  twin: TwinInfo | null
  twinState: TwinState | null
  info: RigInfo | null
  error: string | null
  showTower: boolean
  camera: boolean
  overlay: boolean
  set: (patch: Partial<RigStore>) => void
  toggle: (key: 'showTower' | 'camera' | 'overlay') => void
}

const PREFS_KEY = 'orca-ui.rig-dashboard'

function prefs(): { showTower: boolean; camera: boolean; overlay: boolean } {
  // Camera and overlay always start off (the camera may belong to a running study).
  try {
    const p = JSON.parse(localStorage.getItem(PREFS_KEY) ?? '{}')
    return { showTower: p.showTower ?? false, camera: false, overlay: false }
  } catch {
    return { showTower: false, camera: false, overlay: false }
  }
}

export const useRig = create<RigStore>((set) => ({
  presence: null,
  twin: null,
  twinState: null,
  info: null,
  error: null,
  ...prefs(),
  set: (patch) => set(patch),
  toggle: (key) =>
    set((s) => {
      const next = { ...s, [key]: !s[key] }
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify({ showTower: next.showTower }))
      } catch {
        /* per-viewer convenience only */
      }
      return { [key]: next[key] }
    }),
}))

export const rigConnected = (p: RigPresence | null) => !!p?.connected

const PRESENCE_MS = 3000
const POSE_MS = 200

let users = 0

/** Keeps the rig store fresh while mounted (several users share one poll). */
export function useRigPolling() {
  useEffect(() => {
    users += 1
    if (users > 1) return () => void (users -= 1)
    let alive = true
    let poseTimer = 0
    const { set } = useRig.getState()
    const pose = async () => {
      if (!alive) return
      if (rigConnected(useRig.getState().presence)) {
        try {
          set({ twinState: await visualApi.twinState() })
        } catch {
          /* keep the last pose */
        }
      }
      poseTimer = window.setTimeout(pose, POSE_MS)
    }
    const presence = async () => {
      try {
        const p = await visualApi.rigPresence()
        if (!alive) return
        set({ presence: p, error: null })
        if (p.connected && !useRig.getState().twin) {
          const [twin, info] = await Promise.all([
            visualApi.twin().catch(() => null),
            visualApi.rig().catch(() => null),
          ])
          if (alive) set({ twin, info })
        }
      } catch {
        if (alive) set({ presence: null })
      }
    }
    void presence()
    const timer = window.setInterval(presence, PRESENCE_MS)
    void pose()
    return () => {
      alive = false
      users -= 1
      window.clearInterval(timer)
      window.clearTimeout(poseTimer)
    }
  }, [])
}

/** Refresh presence right away (after a control action). */
export async function refreshRig() {
  try {
    useRig.getState().set({ presence: await visualApi.rigPresence() })
  } catch {
    /* next poll */
  }
}

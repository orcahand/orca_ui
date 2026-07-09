// Teleop plane: latest teleop.state snapshot, the source catalogue, the
// per-source config draft (localStorage-backed), and the cumulative teleop
// log. Fed by streamClient; plain zustand — all topics are event-driven and
// slow (high-rate teleop.targets goes to streamStore, never through here).
//
// Import direction: this store may import appStore/eventLogStore but NEVER
// operationStore (operationStore imports us for useStartGate).

import { create } from 'zustand'
import type {
  OperationLogLine,
  OperationLogPayload,
  TeleopSnapshot,
  TeleopSourceId,
  TeleopSourcesInfo,
} from '../api/types'
import { useAppStore } from './appStore'
import { useEventLogStore } from './eventLogStore'
import { mergeLogPayload } from './logMerge'

const DRAFT_KEY = 'orca-ui.teleop'

export interface TeleopDraft {
  source: TeleopSourceId
  external: boolean // launch the streamer manually instead of spawning it
  camera_index: number
  // True once the user explicitly picked a camera — the scanner's
  // auto-selection stops overriding it.
  camera_manual: boolean
  orientation_gate: boolean
  zmq_addr: string
  avp_ip: string
  manual_wrist_deg: number
  // rmsprop: ~12 ms/frame on CPU (fits 30 Hz). adaptive_analytical: higher
  // quality but ~100 ms/frame on CPU-only machines (~10 Hz teleop).
  retargeter: 'rmsprop' | 'adaptive_analytical'
}

const DRAFT_DEFAULTS: TeleopDraft = {
  source: 'mediapipe',
  external: false,
  camera_index: 0,
  camera_manual: false,
  orientation_gate: true,
  zmq_addr: 'tcp://127.0.0.1:2044',
  avp_ip: '',
  manual_wrist_deg: 0,
  retargeter: 'rmsprop',
}

const storedDraft = ((): TeleopDraft => {
  try {
    return {
      ...DRAFT_DEFAULTS,
      ...JSON.parse(localStorage.getItem(DRAFT_KEY) ?? '{}'),
    }
  } catch {
    return { ...DRAFT_DEFAULTS }
  }
})()

export function isTeleopActive(session: TeleopSnapshot | null): boolean {
  return (
    session !== null &&
    (session.state === 'starting' ||
      session.state === 'preview' ||
      session.state === 'engaged')
  )
}

export function isTeleopEngaged(session: TeleopSnapshot | null): boolean {
  return session !== null && session.state === 'engaged'
}

interface TeleopStoreState {
  session: TeleopSnapshot | null
  sources: TeleopSourcesInfo | null
  // External-mode token from the last start (shown once so the user can
  // launch a remote streamer with it).
  externalToken: string | null
  draft: TeleopDraft
  logRunId: string | null
  logLines: OperationLogLine[]

  setSession(session: TeleopSnapshot): void
  setSources(info: TeleopSourcesInfo | null): void
  setExternalToken(token: string | null): void
  setDraft(patch: Partial<TeleopDraft>): void
  mergeLog(payload: OperationLogPayload): void
}

export const useTeleopStore = create<TeleopStoreState>((set, get) => ({
  session: null,
  sources: null,
  externalToken: null,
  draft: storedDraft,
  logRunId: null,
  logLines: [],

  setSession: (session) => {
    const previous = get().session
    set({ session })
    const changed =
      !previous ||
      previous.session_id !== session.session_id ||
      previous.state !== session.state
    if (!changed) return
    if (session.state === 'error') {
      useAppStore
        .getState()
        .setError(`teleop failed: ${session.error ?? 'unknown error'}`)
      useEventLogStore
        .getState()
        .pushEvent('teleop', `teleop → error: ${session.error ?? 'unknown'}`)
    } else if (session.state !== 'idle') {
      useEventLogStore
        .getState()
        .pushEvent(
          'teleop',
          `teleop → ${session.state}${session.source ? ` (${session.source})` : ''}`,
        )
    } else if (previous && previous.state !== 'idle') {
      useEventLogStore.getState().pushEvent('teleop', 'teleop session stopped')
    }
  },

  setSources: (info) => set({ sources: info }),
  setExternalToken: (token) => set({ externalToken: token }),

  setDraft: (patch) =>
    set((state) => {
      const draft = { ...state.draft, ...patch }
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
      return { draft }
    }),

  mergeLog: (payload) =>
    set((state) => {
      const merged = mergeLogPayload(state.logRunId, state.logLines, payload)
      return merged ?? state
    }),
}))

// ----- derived gating ----------------------------------------------------------

export function useTeleopSession(): TeleopSnapshot | null {
  return useTeleopStore((s) => s.session)
}

// Gate for the Engage button (SessionCard, TeleopBar, dashboard card). The
// backend re-validates everything; this exists for honest tooltips.
export function useEngageGate(): { allowed: boolean; reason: string | null } {
  const session = useTeleopStore((s) => s.session)
  const control = useAppStore((s) => s.control)
  const status = useAppStore((s) => s.status)

  if (!session || session.state !== 'preview') {
    return { allowed: false, reason: 'start a teleop preview first' }
  }
  if (status?.state === 'maintenance') {
    return { allowed: false, reason: 'hand in maintenance' }
  }
  if (!status?.capabilities?.motors) {
    return { allowed: false, reason: 'motor bus unavailable' }
  }
  if (control && control.control_source !== 'manual') {
    return {
      allowed: false,
      reason: `control is owned by ${control.control_owner}`,
    }
  }
  if (!control?.torque_enabled) {
    return { allowed: false, reason: 'enable torque to engage' }
  }
  if (!session.stats.target_hz) {
    return { allowed: false, reason: 'no targets streaming yet' }
  }
  return { allowed: true, reason: null }
}

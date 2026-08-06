// Teleop plane: latest teleop.state snapshot, the source catalogue, the
// per-source config draft (localStorage-backed), and the cumulative teleop
// log. Fed by streamClient; plain zustand — all topics are event-driven and
// slow (high-rate teleop.targets goes to streamStore, never through here).
//
// Import direction: this store may import appStore/eventLogStore but NEVER
// operationStore (operationStore imports us for useStartGate).

import { create } from 'zustand'
import { api } from '../api/rest'
import type {
  OperationLogLine,
  OperationLogPayload,
  TeleopInstallState,
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
  // One-click teleop: when the session reaches preview, enable torque and
  // engage automatically instead of requiring three separate clicks.
  auto_engage: boolean
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
  auto_engage: true,
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
  // Armed by Start when the auto-engage draft option is on; consumed on the
  // first transition into preview (enable torque, then engage).
  autoEngagePending: boolean
  draft: TeleopDraft
  logRunId: string | null
  logLines: OperationLogLine[]
  // orca_teleop checkout install. Separate log ring from the session log: a
  // session starting clears that one, which would wipe the install history
  // exactly when the user acts on it.
  install: TeleopInstallState | null
  installLogRunId: string | null
  installLogLines: OperationLogLine[]

  setSession(session: TeleopSnapshot): void
  setSources(info: TeleopSourcesInfo | null): void
  setExternalToken(token: string | null): void
  setAutoEngagePending(pending: boolean): void
  setDraft(patch: Partial<TeleopDraft>): void
  mergeLog(payload: OperationLogPayload): void
  setInstall(install: TeleopInstallState | null): void
  mergeInstallLog(payload: OperationLogPayload): void
}

// Torque on (if needed), then engage. Fired once per session on entering
// preview; the backend re-validates everything, we just surface failures.
function runAutoEngage() {
  const { status, control, setError } = useAppStore.getState()
  if (!status?.capabilities?.motors) return // camera-only preview: no hand to drive
  const torqueReady = control?.torque_enabled
    ? Promise.resolve(undefined)
    : api.torqueEnable().then(() => undefined)
  torqueReady
    .then(() => api.teleopEngage())
    .catch((error) =>
      setError(
        `auto-engage failed: ${String((error as Error).message ?? error)} — use ⚡ Engage manually`,
      ),
    )
}

export const useTeleopStore = create<TeleopStoreState>((set, get) => ({
  session: null,
  sources: null,
  externalToken: null,
  autoEngagePending: false,
  draft: storedDraft,
  logRunId: null,
  logLines: [],
  install: null,
  installLogRunId: null,
  installLogLines: [],

  setSession: (session) => {
    const previous = get().session
    set({ session })
    if (get().autoEngagePending) {
      if (session.state === 'preview') {
        set({ autoEngagePending: false })
        runAutoEngage()
      } else if (session.state === 'error' || session.state === 'idle') {
        set({ autoEngagePending: false })
      }
    }
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
  setAutoEngagePending: (pending) => set({ autoEngagePending: pending }),

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

  setInstall: (install) => set({ install }),

  mergeInstallLog: (payload) =>
    set((state) => {
      const merged = mergeLogPayload(
        state.installLogRunId,
        state.installLogLines,
        payload,
      )
      return merged
        ? {
            installLogRunId: merged.logRunId,
            installLogLines: merged.logLines,
          }
        : state
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

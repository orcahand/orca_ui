// Control plane for app sessions (Teleop, RL): the latest app.state snapshot,
// what the console remembers per app, and the cumulative app log. Fed by
// streamClient. High-rate app.targets and app.frames go to streamStore.
//
// Import direction: this store may import appStore/eventLogStore but NEVER
// operationStore (operationStore imports us for useStartGate).

import { create } from 'zustand'
import { api } from '../api/rest'
import type {
  AppEntry,
  AppId,
  AppSnapshot,
  OperationLogLine,
  OperationLogPayload,
} from '../api/types'
import { useAppStore } from './appStore'
import { useEventLogStore } from './eventLogStore'
import { mergeLogPayload } from './logMerge'

export function isAppActive(session: AppSnapshot | null): boolean {
  return (
    session !== null &&
    (session.state === 'starting' ||
      session.state === 'preview' ||
      session.state === 'engaged')
  )
}

export function isAppEngaged(session: AppSnapshot | null): boolean {
  return session !== null && session.state === 'engaged'
}

interface AppSessionState {
  session: AppSnapshot | null
  apps: AppEntry[] | null
  logRunId: string | null
  logLines: OperationLogLine[]

  setSession(session: AppSnapshot): void
  setApps(apps: AppEntry[]): void
  refreshApps(): Promise<void>
  mergeLog(payload: OperationLogPayload): void
}

export const useAppSessionStore = create<AppSessionState>((set, get) => ({
  session: null,
  apps: null,
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
    const name = session.title ?? 'app'
    if (session.state === 'error') {
      useAppStore
        .getState()
        .setError(`${name} failed: ${session.error ?? 'unknown error'}`)
      useEventLogStore
        .getState()
        .pushEvent('app', `${name} → error: ${session.error ?? 'unknown'}`)
    } else if (session.state !== 'idle') {
      useEventLogStore.getState().pushEvent('app', `${name} → ${session.state}`)
    } else if (previous && previous.state !== 'idle') {
      useEventLogStore.getState().pushEvent('app', `${name} session ended`)
    }
    // Any end (error too): the app may have sent new settings; show what was saved.
    if (previous && (session.state === 'idle' || session.state === 'error'))
      void get().refreshApps()
  },

  setApps: (apps) => set({ apps }),

  refreshApps: async () => {
    try {
      set({ apps: (await api.appList()).apps })
    } catch {
      /* app sessions may be disabled (--no-apps) */
    }
  },

  mergeLog: (payload) =>
    set((state) => {
      const merged = mergeLogPayload(state.logRunId, state.logLines, payload)
      return merged ?? state
    }),
}))

export function useAppEntry(app: AppId): AppEntry | null {
  return useAppSessionStore((s) => s.apps?.find((a) => a.id === app) ?? null)
}

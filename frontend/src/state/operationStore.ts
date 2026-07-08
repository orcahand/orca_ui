// Operation plane: latest operation.state snapshot + the cumulative
// operation.log merged by seq. Fed by streamClient; plain zustand (no rAF
// fan-out) — both topics are event-driven and slow.

import { create } from 'zustand'
import type {
  ControlSource,
  OperationLogLine,
  OperationLogPayload,
  OperationSnapshot,
} from '../api/types'
import { useAppStore } from './appStore'
import { useEventLogStore } from './eventLogStore'

const LOG_CAP = 500

export function isOperationActive(op: OperationSnapshot | null): boolean {
  return op !== null && op.state !== 'done' && op.state !== 'error'
}

interface OperationStoreState {
  operation: OperationSnapshot | null
  logRunId: string | null
  logLines: OperationLogLine[]

  setOperation(snapshot: OperationSnapshot): void
  mergeLog(payload: OperationLogPayload): void
}

export const useOperationStore = create<OperationStoreState>((set, get) => ({
  operation: null,
  logRunId: null,
  logLines: [],

  setOperation: (snapshot) => {
    const previous = get().operation
    set({ operation: snapshot })
    const changed =
      !previous ||
      previous.run_id !== snapshot.run_id ||
      previous.state !== snapshot.state
    if (!changed) return
    // Terminal snapshots surface on every tab: errors hit the global banner,
    // both terminals land in the Motors tab event log.
    if (snapshot.state === 'error') {
      useAppStore
        .getState()
        .setError(`${snapshot.kind} failed: ${snapshot.error ?? 'unknown error'}`)
      useEventLogStore
        .getState()
        .pushEvent(
          'operation',
          `${snapshot.kind} → error: ${snapshot.error ?? 'unknown'}`,
        )
    } else if (snapshot.state === 'done') {
      useEventLogStore
        .getState()
        .pushEvent('operation', `${snapshot.kind} → done`)
    }
  },

  // The payload is the run's whole bounded buffer (latest-wins coalescing on
  // the server loses nothing that way); append only lines newer than what we
  // have, reset on a new run_id. A reload mid-op resyncs the full log.
  mergeLog: (payload) =>
    set((state) => {
      const reset = payload.run_id !== state.logRunId
      const kept = reset ? [] : state.logLines
      const lastSeq = kept.length > 0 ? kept[kept.length - 1].seq : -1
      const fresh = payload.lines.filter((line) => line.seq > lastSeq)
      if (!reset && fresh.length === 0) return state
      return {
        logRunId: payload.run_id,
        logLines: [...kept, ...fresh].slice(-LOG_CAP),
      }
    }),
}))

// ----- derived gating --------------------------------------------------------

export function useOperationActive(): boolean {
  return useOperationStore((s) => isOperationActive(s.operation))
}

export function useControlOwner(): string {
  return useAppStore((s) => s.control?.control_owner ?? 'manual')
}

export interface ControlGate {
  source: ControlSource
  owner: string
  // False while an operation/teleop owns the target channel or the hand is
  // in maintenance; `reason` then names the owner for tooltips.
  manualAllowed: boolean
  reason: string | null
}

export function useControlGate(): ControlGate {
  const source = useAppStore((s) => s.control?.control_source ?? 'manual')
  const owner = useAppStore((s) => s.control?.control_owner ?? 'manual')
  const maintenance = useAppStore((s) => s.status?.state === 'maintenance')
  if (maintenance) {
    return { source, owner, manualAllowed: false, reason: 'hand in maintenance' }
  }
  if (source !== 'manual') {
    return {
      source,
      owner,
      manualAllowed: false,
      reason: `control is owned by ${owner}`,
    }
  }
  return { source, owner, manualAllowed: true, reason: null }
}

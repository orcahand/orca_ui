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
import { mergeLogPayload } from './logMerge'
import { isTeleopEngaged, useTeleopStore } from './teleopStore'

export function isOperationActive(op: OperationSnapshot | null): boolean {
  return op !== null && op.state !== 'done' && op.state !== 'error'
}

// Wire names the UI calls something else. The guided setup run is "wizard"
// on the API; everywhere a user can see it, it is the full setup.
const OPERATION_LABELS: Record<string, string> = { wizard: 'full setup' }

export function operationLabel(kind: string): string {
  return OPERATION_LABELS[kind] ?? kind
}

interface OperationStoreState {
  operation: OperationSnapshot | null
  logRunId: string | null
  logLines: OperationLogLine[]

  // null clears the plane (REST resync after a backend restart found no op).
  setOperation(snapshot: OperationSnapshot | null): void
  mergeLog(payload: OperationLogPayload): void
}

export const useOperationStore = create<OperationStoreState>((set, get) => ({
  operation: null,
  logRunId: null,
  logLines: [],

  setOperation: (snapshot) => {
    const previous = get().operation
    set({ operation: snapshot })
    if (!snapshot) return
    const changed =
      !previous ||
      previous.run_id !== snapshot.run_id ||
      previous.state !== snapshot.state
    if (!changed) return
    // Terminal snapshots surface on every tab: errors hit the global banner,
    // both terminals land in the Motors tab event log.
    const label = operationLabel(snapshot.kind)
    if (snapshot.state === 'error') {
      useAppStore
        .getState()
        .setError(`${label} failed: ${snapshot.error ?? 'unknown error'}`)
      useEventLogStore
        .getState()
        .pushEvent(
          'operation',
          `${label} → error: ${snapshot.error ?? 'unknown'}`,
        )
    } else if (snapshot.state === 'done') {
      useEventLogStore.getState().pushEvent('operation', `${label} → done`)
    }
  },

  // Cumulative payload, seq-merged (see logMerge.ts). A reload mid-op
  // resyncs the full log.
  mergeLog: (payload) =>
    set((state) => {
      const merged = mergeLogPayload(state.logRunId, state.logLines, payload)
      return merged ?? state
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

// Gate for operation *start* buttons (Setup cards, demo/replay/record):
// blocked while another operation is active or a required capability is
// missing; `reason` feeds the tooltip/label.
export function useStartGate(requires: 'motors' | 'encoders'): {
  blocked: boolean
  reason: string | null
} {
  const activeKind = useOperationStore((s) =>
    isOperationActive(s.operation) ? s.operation!.kind : null,
  )
  const teleopEngaged = useTeleopStore((s) => isTeleopEngaged(s.session))
  const caps = useAppStore((s) => s.status?.capabilities)
  if (activeKind) {
    return {
      blocked: true,
      reason: `${operationLabel(activeKind)} is running — stop it first`,
    }
  }
  // Mirrors the backend's require_manual_control gate on operation start.
  // A teleop PREVIEW deliberately does not block — it owns nothing.
  if (teleopEngaged) {
    return {
      blocked: true,
      reason: 'teleop is engaged — disengage first',
    }
  }
  if (!caps?.[requires]) {
    return {
      blocked: true,
      reason:
        requires === 'motors'
          ? 'motor bus unavailable'
          : 'joint encoders unavailable',
    }
  }
  return { blocked: false, reason: null }
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

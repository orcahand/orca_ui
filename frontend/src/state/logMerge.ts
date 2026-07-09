// Seq-merge for CUMULATIVE log payloads ({run_id, next_seq, lines}) — the
// hub coalesces latest-wins, so every publish carries the run's whole bounded
// buffer; append only lines newer than what we have, reset on a new run_id.
// Shared by the operation and teleop log stores.

import type { OperationLogLine, OperationLogPayload } from '../api/types'

export const LOG_CAP = 500

export function mergeLogPayload(
  logRunId: string | null,
  logLines: OperationLogLine[],
  payload: OperationLogPayload,
): { logRunId: string | null; logLines: OperationLogLine[] } | null {
  const reset = payload.run_id !== logRunId
  const kept = reset ? [] : logLines
  const lastSeq = kept.length > 0 ? kept[kept.length - 1].seq : -1
  const fresh = payload.lines.filter((line) => line.seq > lastSeq)
  if (!reset && fresh.length === 0) return null // no change
  return {
    logRunId: payload.run_id,
    logLines: [...kept, ...fresh].slice(-LOG_CAP),
  }
}

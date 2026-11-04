// The run's temperature traces, for the chart: the backend keeps a decimated
// history per run; the page fetches it once per run (so a reload or a page
// opened mid-run sees the whole curve) and appends from the operation's live
// snapshot in lockstep with the backend's point count.

import { api } from '../api/rest'
import type { OperationSnapshot, ThermalExtra } from '../api/types'

export interface TraceSet {
  runId: string | null
  t: number[]
  temps: Map<string, (number | null)[]>
  points: number // backend's count when last synced
  limitC: number | null
}

export const thermalTraces: TraceSet = {
  runId: null,
  t: [],
  temps: new Map(),
  points: 0,
  limitC: null,
}

let fetching: string | null = null
const listeners = new Set<() => void>()

export function onTracesChange(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function notify() {
  listeners.forEach((cb) => cb())
}

async function refetch(runId: string) {
  if (fetching === runId) return
  fetching = runId
  try {
    const h = await api.thermalHistory()
    if (h.run_id !== runId) return
    thermalTraces.runId = runId
    thermalTraces.t = h.t_s
    thermalTraces.temps = new Map(Object.entries(h.temps))
    thermalTraces.points = h.t_s.length
    notify()
  } catch {
    /* next snapshot retries */
  } finally {
    fetching = null
  }
}

/** Feed every operation snapshot; keeps the traces current for the chart. */
export function trackThermalOperation(op: OperationSnapshot | null): void {
  if (!op || op.kind !== 'motor_thermal') return
  const extra = op.extra as ThermalExtra | null
  if (!extra) return
  thermalTraces.limitC = extra.temp_limit_c
  if (thermalTraces.runId !== op.run_id || extra.history_points < thermalTraces.points) {
    // New run, or the backend decimated: take its copy.
    void refetch(op.run_id)
    return
  }
  if (extra.history_points > thermalTraces.points) {
    if (extra.history_points > thermalTraces.points + 1) {
      void refetch(op.run_id)
      return
    }
    thermalTraces.t.push(extra.elapsed_s)
    for (const [id, temp] of Object.entries(extra.live.temps)) {
      let series = thermalTraces.temps.get(id)
      if (!series) {
        series = new Array(thermalTraces.t.length - 1).fill(null)
        thermalTraces.temps.set(id, series)
      }
      series.push(temp ?? null)
    }
    thermalTraces.points = extra.history_points
    notify()
  }
}

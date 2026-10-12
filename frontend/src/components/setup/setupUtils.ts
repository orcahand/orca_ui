// Helpers shared by the Setup steps, kept out of the component files.

import type { OperationSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'

export function failToBanner(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
}

const runInKey = (model: string) => `orca.runIn.done.${model}`

export function readRunInDone(model: string | undefined): string | null {
  if (!model) return null
  try {
    return localStorage.getItem(runInKey(model))
  } catch {
    return null
  }
}

// A stopped run also ends "done", but without a result.
export function runInCompleted(operation: OperationSnapshot | null): boolean {
  return operation?.kind === 'run_in' && operation.state === 'done' && operation.result != null
}

export function writeRunInDone(model: string, iso: string): void {
  try {
    localStorage.setItem(runInKey(model), iso)
  } catch {
    /* storage unavailable: the tick is only for this page */
  }
}

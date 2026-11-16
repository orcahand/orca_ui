// Helpers shared by the Setup steps, kept out of the component files.

import type { OperationSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'

export function failToBanner(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' })
}

// Kept per physical hand (its id in the hand store): another hand of the same model has its own.
const runInKey = (handId: string) => `orca.runIn.done.hand.${handId}`

export function readRunInDone(handId: string | null | undefined): string | null {
  if (!handId) return null
  try {
    return localStorage.getItem(runInKey(handId))
  } catch {
    return null
  }
}

// A stopped run also ends "done", but without a result.
export function runInCompleted(operation: OperationSnapshot | null): boolean {
  return operation?.kind === 'run_in' && operation.state === 'done' && operation.result != null
}

export function writeRunInDone(handId: string, iso: string): void {
  try {
    localStorage.setItem(runInKey(handId), iso)
  } catch {
    /* storage unavailable: the tick is only for this page */
  }
}

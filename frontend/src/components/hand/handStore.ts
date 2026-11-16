// Small helpers shared by the views of the connected hand's own files.

import { api, ApiError } from '../../api/rest'
import type { HandStoreInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'

export function refreshHandInfo(): Promise<void> {
  return api
    .handInfo()
    .then(useAppStore.getState().setHandInfo)
    .catch(() => undefined)
}

export function handFailed(what: string) {
  return (e: unknown) =>
    useAppStore
      .getState()
      .setError(e instanceof ApiError ? `Could not ${what}: ${e.message}` : `Could not ${what}.`)
}

export function handLabel(hand: HandStoreInfo): string {
  return hand.nickname ? `${hand.nickname} · ${hand.id}` : hand.id
}

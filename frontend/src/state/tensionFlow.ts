// The tensioning dialogs' settings and open/dismissed state. Guided
// tensioning is scored against the travel baseline; simple tensioning is the
// hold dialog: activate the current, ratchet. The dialogs are mounted once
// (TensionDialogs), so any flow that tensions gets the same UI for the same hand.

import { create } from 'zustand'
import type { OperationSnapshot } from '../api/types'

// Board versions are major*100 + minor*10 + patch; boards provisioned earlier report 2 or 21.
export const V20 = 200
export const V21 = 210
export const V211 = 211
// How far the finger motors slowly turn counterclockwise while you ratchet, and what one
// "Pull more" adds. Mirror the backend's tension.py.
export const DEFAULT_OFFSET_DEG = 15
export const EXTRA_DEG = 15
export const PULL_MORE = 'Pull more'
// The slack test winds a held joint's spool at this current: enough to start the gearbox.
export const DEFAULT_SLACK_CURRENT_MA = 60
export const SLACK_CURRENT_CHOICES = [40, 60, 80, 100] as const

export function normalizeHardwareVersion(version: number): number {
  return version < 10 ? version * 100 : version < 100 ? version * 10 : version
}

export function formatHardwareVersion(version: number | null | undefined): string {
  if (version == null) return '?'
  const v = normalizeHardwareVersion(version)
  return `v${Math.floor(v / 100)}.${Math.floor(v / 10) % 10}.${v % 10}`
}

export function isV21Family(version: number | null | undefined): boolean {
  return version != null && Math.floor(normalizeHardwareVersion(version) / 10) === V21 / 10
}

interface TensionFlowState {
  // Hold dialog opened by the operator, before any operation exists.
  holdOpen: boolean
  openHold: (staleRunId: string | null) => void
  closeHold: () => void
  // Wind the tendons to the hard stops before the hold.
  wind: boolean
  setWind: (wind: boolean) => void
  // The run whose dialog the operator closed; a later run shows again.
  dismissed: string | null
  dismiss: (runId: string | null) => void
  slackCurrentMa: number
  setSlackCurrentMa: (ma: number) => void
  // The finished sweep whose dialog holds the motors for its clicks; the hold
  // ("tension") run shows inside that dialog while this is set.
  sweepRatchet: OperationSnapshot | null
  setSweepRatchet: (sweep: OperationSnapshot | null) => void
  // The slack test's clicks per joint, listed in the hold dialog it went on to.
  holdClicks: Record<string, number> | null
  setHoldClicks: (clicks: Record<string, number> | null) => void
}

export const useTensionFlow = create<TensionFlowState>((set) => ({
  holdOpen: false,
  openHold: (staleRunId) => set({ holdOpen: true, dismissed: staleRunId, sweepRatchet: null, holdClicks: null }),
  closeHold: () => set({ holdOpen: false }),
  wind: false,
  setWind: (wind) => set({ wind }),
  dismissed: null,
  dismiss: (dismissed) => set({ dismissed }),
  slackCurrentMa: DEFAULT_SLACK_CURRENT_MA,
  setSlackCurrentMa: (slackCurrentMa) => set({ slackCurrentMa }),
  sweepRatchet: null,
  setSweepRatchet: (sweepRatchet) => set({ sweepRatchet }),
  holdClicks: null,
  setHoldClicks: (holdClicks) => set({ holdClicks }),
}))

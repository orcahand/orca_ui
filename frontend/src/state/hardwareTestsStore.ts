// Hardware-tests tab state: the backend's session polled from GET /state
// (1 s, 0.5 s while the automatic run is busy) and the step the tester has open.

import { useEffect } from 'react'
import { create } from 'zustand'
import type { HwDecision, HwFeature, HwPlanSummary, HwSession, HwStep } from '../api/hardwareTests'
import { DECIDED_STATUSES, hwApi } from '../api/hardwareTests'
import { useAppStore } from './appStore'

const POLL_MS = 1000
const POLL_BUSY_MS = 500

export interface HwStepRef {
  step: HwStep
  feature: HwFeature
}

// Hands-on: a person acts or looks. Everything else belongs to the automatic run.
export function isHandsOn(step: HwStep): boolean {
  return step.hands_on ?? (step.kind === 'manual' || (step.kind === 'observe' && !step.check))
}

export function allSteps(session: HwSession | null): HwStepRef[] {
  if (!session) return []
  return session.features.flatMap((feature) => feature.steps.map((step) => ({ step, feature })))
}

export function findStep(session: HwSession | null, id: string | null): HwStepRef | null {
  if (!id) return null
  return allSteps(session).find((ref) => ref.step.id === id) ?? null
}

export function undecidedHandsOn(session: HwSession | null): HwStepRef[] {
  return allSteps(session).filter(
    ({ step }) => isHandsOn(step) && step.applicable && !DECIDED_STATUSES.has(step.result.status),
  )
}

interface HardwareTestsState {
  // null until the first GET /state answers.
  enabled: boolean | null
  plans: HwPlanSummary[]
  session: HwSession | null
  defaultLabel: string | null
  benchDir: string | null
  // Polling trouble (backend unreachable, router missing); cleared on success.
  pollError: string | null
  selected: string | null
  busy: boolean

  refresh(): Promise<void>
  startSession(planId: string, label: string): Promise<void>
  endSession(): Promise<void>
  select(stepId: string | null): Promise<void>
  closeOpen(): Promise<void>
  decide(stepId: string, status: HwDecision, note: string): Promise<void>
  runAuto(opts?: { stepIds?: string[]; force?: boolean }): Promise<void>
  stopAuto(): Promise<void>
}

function fail(error: unknown): void {
  useAppStore.getState().setError(`Tests: ${String((error as Error).message ?? error)}`)
}

let refreshing: Promise<void> | null = null

export const useHardwareTestsStore = create<HardwareTestsState>((set, get) => {
  const apply = (session: HwSession) => set({ session })

  // Runs an action that answers with the session; errors go to the global banner.
  const act = async (call: () => Promise<HwSession>) => {
    set({ busy: true })
    try {
      apply(await call())
    } catch (error) {
      fail(error)
    } finally {
      set({ busy: false })
    }
  }

  return {
    enabled: null,
    plans: [],
    session: null,
    defaultLabel: null,
    benchDir: null,
    pollError: null,
    selected: null,
    busy: false,

    refresh: () => {
      if (refreshing) return refreshing
      refreshing = hwApi
        .state()
        .then((state) => {
          const previous = get().session
          set({
            enabled: state.enabled,
            plans: state.plans,
            session: state.session,
            defaultLabel: state.default_label ?? null,
            benchDir: state.bench_dir ?? null,
            pollError: null,
          })
          // After a reload, reopen what the backend still records as open.
          if (!previous && state.session?.open_step && !get().selected) {
            set({ selected: state.session.open_step })
          }
        })
        .catch((error) => set({ pollError: String((error as Error).message ?? error) }))
        .finally(() => {
          refreshing = null
        })
      return refreshing
    },

    startSession: async (planId, label) => {
      await act(() => hwApi.startSession(planId, label))
      await get().refresh()
    },

    endSession: async () => {
      set({ busy: true })
      try {
        const open = get().session?.open_step
        if (open) await hwApi.closeStep(open).catch(() => undefined)
        await hwApi.endSession()
        set({ selected: null })
        await get().refresh()
      } catch (error) {
        fail(error)
      } finally {
        set({ busy: false })
      }
    },

    // Selecting an applicable hands-on step opens it (live readings are recorded
    // while open); viewing any other step leaves the open one recording.
    select: async (stepId) => {
      const { session, selected } = get()
      if (stepId === selected) return
      set({ selected: stepId })
      const open = session?.open_step ?? null
      const next = findStep(session, stepId)
      if (!next || !isHandsOn(next.step) || !next.step.applicable || open === stepId) return
      try {
        if (open) apply(await hwApi.closeStep(open))
        apply(await hwApi.openStep(next.step.id))
      } catch (error) {
        fail(error)
      }
    },

    closeOpen: async () => {
      const open = get().session?.open_step
      if (open) await act(() => hwApi.closeStep(open))
    },

    decide: (stepId, status, note) => act(() => hwApi.decide(stepId, status, note)),
    runAuto: (opts) => act(() => hwApi.runAuto(opts)),
    stopAuto: () => act(() => hwApi.stopAuto()),
  }
})

export function useHardwareTestsPolling(): void {
  useEffect(() => {
    let timer: number | undefined
    let stopped = false
    const tick = async () => {
      await useHardwareTestsStore.getState().refresh()
      if (stopped) return
      const auto = useHardwareTestsStore.getState().session?.auto.state ?? 'idle'
      timer = window.setTimeout(tick, auto === 'idle' ? POLL_MS : POLL_BUSY_MS)
    }
    void tick()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [])
}

type FlagCarrier = { hardware_tests?: boolean } | null

// The tab shows when the backend says so: hand info's `hardware_tests`, or
// GET /state's `enabled` while no hand info has arrived.
export function useHardwareTestsFlag(): boolean {
  const carried = useAppStore((s) => (s.handInfo as FlagCarrier)?.hardware_tests)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const fromState = useHardwareTestsStore((s) => s.enabled)
  useEffect(() => {
    if (carried === undefined && wsConnected) void useHardwareTestsStore.getState().refresh()
  }, [carried, wsConnected])
  return carried ?? fromState ?? false
}

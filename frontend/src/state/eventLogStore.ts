// Client-side accumulation of notable events (status transitions, backend
// errors, operation terminals) for the Motors tab's event log. Bounded —
// no backend storage; the buffer lives for the page session.

import { create } from 'zustand'

export interface UiEvent {
  id: number
  t: number // ms epoch
  kind: 'status' | 'error' | 'operation'
  text: string
}

const EVENT_CAP = 500

let nextId = 0

interface EventLogState {
  events: UiEvent[]
  pushEvent(kind: UiEvent['kind'], text: string): void
  clear(): void
}

export const useEventLogStore = create<EventLogState>((set) => ({
  events: [],
  pushEvent: (kind, text) =>
    set((state) => ({
      events: [
        ...state.events,
        { id: nextId++, t: Date.now(), kind, text },
      ].slice(-EVENT_CAP),
    })),
  clear: () => set({ events: [] }),
}))

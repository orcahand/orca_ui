// "What's new": the changelog the backend ships, and whether this release's
// notes have been ticked away. The tick lives in an untracked indicator file
// beside the backend, not in this browser — so it follows the install rather
// than whoever happens to be looking at it.

import { create } from 'zustand'
import { api } from '../api/rest'
import type { ChangelogDoc } from '../api/types'

interface ChangelogState {
  doc: ChangelogDoc | null
  isOpen: boolean
  /** The auto-open fires at most once per page load, however long it waited. */
  autoOpened: boolean
  load(): Promise<void>
  open(): void
  close(dismissed: boolean): void
  markAutoOpened(): void
}

export const useChangelogStore = create<ChangelogState>((set, get) => ({
  doc: null,
  isOpen: false,
  autoOpened: false,

  load: async () => {
    try {
      set({ doc: await api.changelog() })
    } catch {
      // No changelog is not worth an error banner; the button just stays quiet.
    }
  },

  open: () => set({ isOpen: true }),

  close: (dismissed) => {
    set({ isOpen: false })
    if (dismissed === (get().doc?.dismissed ?? false)) return
    // The backend answers with the state it wrote, so a failed write leaves
    // the button showing unread rather than claiming the tick stuck.
    void api
      .changelogSeen(dismissed)
      .then((doc) => set({ doc }))
      .catch(() => undefined)
  },

  markAutoOpened: () => set({ autoOpened: true }),
}))

/** True while this release's notes have not been ticked away. */
export function hasUnseenChangelog(state: ChangelogState): boolean {
  return Boolean(state.doc?.latest_version) && !state.doc?.dismissed
}

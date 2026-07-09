// Slider -> backend command path: leading+trailing throttle at 20 Hz, multi-
// joint coalescing, WS with REST fallback.

import { api } from '../api/rest'
import { sendCommand } from '../api/streamClient'
import { useAppStore } from './appStore'

const FLUSH_MS = 50

const pending = new Map<string, number>()
let timer: number | null = null

export function sendTarget(joint: string, deg: number): void {
  pending.set(joint, deg)
  if (timer === null) {
    flush() // leading edge: first movement reacts instantly
    timer = window.setTimeout(trailing, FLUSH_MS)
  }
}

function trailing(): void {
  timer = null
  if (pending.size) {
    flush()
    timer = window.setTimeout(trailing, FLUSH_MS)
  }
}

function flush(): void {
  if (!pending.size) return
  // A trailing flush can race a control-source change (operation start,
  // teleop engage): the sliders are already disabled, so drop the stale
  // targets instead of bouncing a 409 into the error banner.
  const control = useAppStore.getState().control
  if (control && control.control_source !== 'manual') {
    pending.clear()
    return
  }
  const angles = Object.fromEntries(pending)
  pending.clear()
  if (!sendCommand(angles)) {
    api.jointsTarget(angles).catch((error) => {
      useAppStore.getState().setError(String(error.message ?? error))
    })
  }
}

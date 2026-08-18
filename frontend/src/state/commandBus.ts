// Slider -> backend command path: one coalesced send per animation frame,
// multi-joint coalescing, WS with REST fallback.
//
// Paced by rAF rather than a fixed timer so the setpoint stream matches the
// rate the browser delivers pointer moves at. The joint loop runs a 100 Hz PI
// against whatever setpoint it last received, so a setpoint that only steps
// every 50 ms makes the loop chase a staircase and the joint ratchets
// visibly. scripts/manual_control.py sends on every Tk motion event for the
// same reason, and is smooth because of it.

import { api } from '../api/rest'
import { sendCommand } from '../api/streamClient'
import { useAppStore } from './appStore'

const pending = new Map<string, number>()
let frame: number | null = null
let restInFlight = false

export function sendTarget(joint: string, deg: number): void {
  pending.set(joint, deg)
  if (frame === null) frame = requestAnimationFrame(flush)
}

function flush(): void {
  frame = null
  if (!pending.size) return
  // A flush can race a control-source change (operation start, teleop
  // engage): the sliders are already disabled, so drop the stale targets
  // instead of bouncing a 409 into the error banner.
  const control = useAppStore.getState().control
  if (control && control.control_source !== 'manual') {
    pending.clear()
    return
  }
  // WS down and the previous POST hasn't settled: hold the targets and retry
  // next frame rather than queueing a request per frame.
  if (restInFlight) {
    frame = requestAnimationFrame(flush)
    return
  }
  const angles = Object.fromEntries(pending)
  pending.clear()
  if (sendCommand(angles)) return
  restInFlight = true
  api
    .jointsTarget(angles)
    .catch((error) => {
      useAppStore.getState().setError(String(error.message ?? error))
    })
    .finally(() => {
      restInFlight = false
    })
}

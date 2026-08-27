// The E-stop, sharing its header slot with its idle alter ego: when there is
// nothing to stop (torque off, nothing owning control) the same button reads
// "Enable Torque" and arms the hand instead. No confirm dialog either way —
// POST /api/estop is never-raising and state-aware server-side (stops the
// op, disables torque where a session exists, stops the mock sweeper).

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useEventLogStore } from '../../state/eventLogStore'

export function EStopButton() {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState(false)

  // Torque-free record/teleop sessions still need stopping, so only a fully
  // idle hand flips the button to Enable Torque.
  const idle =
    control != null &&
    !control.torque_enabled &&
    control.control_source === 'manual'

  const fire = async () => {
    try {
      const { report } = await api.estop()
      const summary = Object.entries(report)
        .map(([key, value]) => `${key}=${String(value)}`)
        .join(' ')
      useEventLogStore.getState().pushEvent('operation', `E-STOP: ${summary}`)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  const arm = async () => {
    setBusy(true)
    try {
      await api.torqueEnable()
      useEventLogStore.getState().pushEvent('operation', 'torque enabled')
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  if (idle) {
    return (
      <button
        className="btn-estop btn-torque-arm"
        disabled={!wsConnected || busy}
        title={
          wsConnected
            ? 'torque is off — enable it (motors hold their current pose)'
            : 'backend offline'
        }
        onClick={() => void arm()}
      >
        ⏻ Enable Torque
      </button>
    )
  }

  return (
    <button
      className="btn-estop"
      disabled={!wsConnected}
      title={
        wsConnected
          ? 'emergency stop: stop operation + disable torque'
          : 'backend offline'
      }
      onClick={() => void fire()}
    >
      ■ E-STOP
    </button>
  )
}

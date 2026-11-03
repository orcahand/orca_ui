// Torque strip: shows on every tab whenever the motors are energized, so the
// control that de-energizes the hand is never a tab away. Stacks with the
// operation and teleop bars — torque is on during most operations, and the
// operator may need to drop it mid-run.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function TorqueBar() {
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState(false)

  if (!torqueOn) return null

  const disable = async () => {
    setBusy(true)
    try {
      await api.torqueDisable()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="transport-bar torque-live">
      <span className="transport-kind">⚡ torque</span>
      <span className="transport-detail">
        motors energized — the hand holds position and resists being moved
      </span>
      <div className="transport-controls">
        <button
          className="btn btn-danger"
          disabled={busy}
          onClick={() => void disable()}
        >
          Disable Torque
        </button>
      </div>
    </div>
  )
}

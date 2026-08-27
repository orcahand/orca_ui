// Disconnect / Reconnect, beside the status pill.
//
// The backend's connect ladder is relentless on purpose: it exists so a hand
// that was off, or briefly unplugged, comes back without anyone touching the
// console. Disconnect is the way to say "not now" — the session closes, torque
// goes off, and nothing reopens the ports until Reconnect asks it to. That is
// what makes a power cycle, a cable move, or an orca_core script on the same
// bus possible with the console still open.
//
// Reconnect stays live in both states: while connected it drops and redials,
// and while released it is the way back. So Disconnect is the only one that
// can be a no-op, and it is the one that disables.

import { useState } from 'react'
import { api, ApiError } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function LinkControls() {
  const status = useAppStore((s) => s.status)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState<'disconnect' | 'reconnect' | null>(null)

  const released = status?.released ?? false

  async function run(action: 'disconnect' | 'reconnect') {
    setBusy(action)
    try {
      const result =
        action === 'disconnect' ? await api.disconnect() : await api.reconnect()
      // The status topic will carry this too; taking it from the response
      // means the buttons settle immediately rather than a tick later.
      if (result?.status) useAppStore.getState().setStatus(result.status)
      setError(null)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Could not ${action}: ${e.message}`
          : `Could not ${action}.`,
      )
    } finally {
      setBusy(null)
    }
  }

  return (
    <span className="link-controls">
      <button
        type="button"
        className="btn btn-secondary link-btn"
        disabled={!wsConnected || released || busy !== null}
        title={
          released
            ? 'Already disconnected — the ports are free.'
            : 'Close the session and leave the ports free (torque off). Nothing reconnects until you press Reconnect.'
        }
        onClick={() => void run('disconnect')}
      >
        {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}
      </button>
      <button
        type="button"
        className={`btn link-btn ${released ? 'btn-primary' : 'btn-secondary'}`}
        disabled={!wsConnected || busy !== null}
        title={
          released
            ? 'Search for the hand again and connect.'
            : 'Drop the session and connect again from scratch.'
        }
        onClick={() => void run('reconnect')}
      >
        {busy === 'reconnect' ? 'Connecting…' : 'Reconnect'}
      </button>
    </span>
  )
}

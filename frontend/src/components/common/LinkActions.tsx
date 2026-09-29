// Rescan / Reconnect, on the dashboard and in the Motors tab.
//
// Rescan only exists while the config declares hardware this session did not
// get: the backend stops probing after a few tries, so this is the operator
// saying "it is there now, look again" without dropping the session. For a
// device the hand itself refused the backend reconnects instead, because a
// port probe cannot undo a refusal.
//
// Reconnect drops the session and redials from scratch. The header carries
// one too; this is the copy that sits next to the health strip that just told
// you something is wrong.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function LinkActions() {
  const status = useAppStore((s) => s.status)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState<'rescan' | 'reconnect' | null>(null)

  const missing = status?.missing ?? []
  const rescanning = status?.rescanning ?? false

  const run = async (action: 'rescan' | 'reconnect') => {
    setBusy(action)
    try {
      const result =
        action === 'rescan' ? await api.rescan() : await api.reconnect()
      if (result?.status) useAppStore.getState().setStatus(result.status)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      {missing.length > 0 && (
        <button
          className="btn btn-secondary"
          disabled={rescanning || busy !== null}
          title={
            rescanning
              ? `looking for ${missing.join(' + ')} now`
              : `probe again for ${missing.join(' + ')} — the backend stopped ` +
                'looking after a few tries. Plug it in, or calibrate the ' +
                'encoder pass, then rescan.'
          }
          onClick={() => void run('rescan')}
        >
          {rescanning
            ? `rescanning for ${missing.join(' + ')}…`
            : `rescan for missing ${missing.join(' + ')}`}
        </button>
      )}
      <button
        className="btn btn-secondary"
        disabled={busy !== null}
        title="Drop the session and connect again from scratch."
        onClick={() => void run('reconnect')}
      >
        {busy === 'reconnect' ? 'Connecting…' : 'Reconnect'}
      </button>
    </>
  )
}

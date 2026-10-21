// The only way back from a latched hardware error short of power-cycling the
// hand. Torque is restored afterwards when the hand has torque, and the
// motor's reboot count starts again - a manual reboot is the operator taking
// the decision back. If the underlying fault is still there it latches again
// the next time it is driven, which is itself the useful diagnostic.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function RebootButton({
  id,
  needsCooling,
}: {
  // Motor ids arrive as object keys, so callers carry them as strings.
  id: string
  needsCooling: boolean
}) {
  const [busy, setBusy] = useState(false)
  const setError = useAppStore((s) => s.setError)
  const supported = useAppStore((s) => s.handInfo?.reboot_supported ?? true)
  if (!supported) return null
  return (
    <button
      type="button"
      className="btn btn-secondary reboot-btn"
      disabled={busy}
      title={
        needsCooling
          ? 'Reboot this motor. It is a heat fault — let it cool first or it latches again immediately.'
          : 'Reboot this motor to clear the latch. Its torque is restored if the hand has torque, and its reboot count starts again. If the fault persists it latches again when next driven.'
      }
      onClick={() => {
        setBusy(true)
        api
          .rebootMotor(Number(id))
          .then((r) => {
            if (r.cleared === null) {
              setError(`motor ${id} did not answer after the reboot — check it before driving`)
            } else if (r.cleared) {
              setError(null)
            } else {
              setError(`motor ${id} re-latched immediately: ${(r.hw_error_flags ?? []).join(' + ')} — the cause is still present`)
            }
          })
          .catch((e) => setError(String((e as Error).message ?? e)))
          .finally(() => setBusy(false))
      }}
    >
      {busy ? '…' : 'reboot'}
    </button>
  )
}

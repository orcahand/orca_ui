import { useEffect, useRef } from 'react'
import type { TorqueOffFailed } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'

// Motors left holding are reported as a routine lets go, often once its dialog
// is gone (Cancel, Hide) or for a run with none: the banner carries it for any
// operation, once per run.
function useTorqueOffBanner() {
  const operation = useOperationStore((s) => s.operation)
  const failed = (operation?.extra as { torque_off_failed?: TorqueOffFailed } | null)?.torque_off_failed
  const runId = operation?.run_id
  const reported = useRef<string | null>(null)
  useEffect(() => {
    if (!failed || !runId || reported.current === runId) return
    reported.current = runId
    const named = failed.motors.map((m, i) => `M${m}${failed.joints[i] ? ` (${failed.joints[i]})` : ''}`).join(', ')
    useAppStore
      .getState()
      .setError(`Torque off was not confirmed on ${named}: they may still be holding. Press E-STOP or power-cycle the hand.`)
  }, [failed, runId])
}

export function ErrorBanner() {
  const error = useAppStore((s) => s.error)
  const setError = useAppStore((s) => s.setError)
  useTorqueOffBanner()
  if (!error) return null
  return (
    <div className="error-panel">
      <span className="error-message">{error}</span>
      <button className="btn btn-secondary" onClick={() => setError(null)}>
        Dismiss
      </button>
    </div>
  )
}

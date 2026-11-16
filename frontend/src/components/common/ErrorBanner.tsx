import { api } from '../../api/rest'
import type { MotorsHolding } from '../../api/types'
import { useAppStore } from '../../state/appStore'

// Motors an operation could not switch off get their own banner, so another
// error never replaces it; the backend clears it once a connection confirms them off.
function HoldingBanner({ holding }: { holding: MotorsHolding }) {
  const setError = useAppStore((s) => s.setError)
  const dismiss = () =>
    void api.motorsHoldingDismiss().catch((e: Error) => setError(String(e?.message ?? e)))
  const named = holding.motors
    .map((m, i) => `M${m}${holding.joints[i] ? ` (${holding.joints[i]})` : ''}`)
    .join(', ')
  return (
    <div className={holding.confirmed ? 'error-panel holding-confirmed' : 'error-panel'}>
      <span className="error-message">
        {holding.confirmed
          ? 'Torque off is now confirmed on all motors.'
          : `Torque off was not confirmed on ${named}: they may still be holding. Press E-STOP or power-cycle the hand.`}
      </span>
      <button className="btn btn-secondary" onClick={dismiss}>
        Dismiss
      </button>
    </div>
  )
}

export function ErrorBanner() {
  const error = useAppStore((s) => s.error)
  const setError = useAppStore((s) => s.setError)
  const holding = useAppStore((s) => s.control?.motors_holding ?? null)
  return (
    <>
      {holding && <HoldingBanner holding={holding} />}
      {error && (
        <div className="error-panel">
          <span className="error-message">{error}</span>
          <button className="btn btn-secondary" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}
    </>
  )
}

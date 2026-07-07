import { useAppStore } from '../../state/appStore'

export function ErrorBanner() {
  const error = useAppStore((s) => s.error)
  const setError = useAppStore((s) => s.setError)
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

// The E-stop. No confirm dialog — POST /api/estop is never-raising and
// state-aware server-side (stops the op, disables torque where a session
// exists, stops the mock sweeper). Disabled only while the backend is
// unreachable.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useEventLogStore } from '../../state/eventLogStore'

export function EStopButton() {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const setError = useAppStore((s) => s.setError)

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

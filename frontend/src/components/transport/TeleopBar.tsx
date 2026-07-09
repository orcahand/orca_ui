// Teleop transport strip: shows for ANY live teleop session (a visible
// PREVIEW badge tells the operator a retargeting pipeline is hot before it
// can take the hand), engage/disengage reachable from every tab. Stacks
// under the operation bar — preview + operation coexisting is legitimate;
// engaged + operation is impossible by the arbiter.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useEngageGate, useTeleopStore } from '../../state/teleopStore'
import { TeleopStateBadge, TrackingDot } from '../teleop/SessionCard'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function TeleopBar() {
  const session = useTeleopStore((s) => s.session)
  const engageGate = useEngageGate()
  const [dismissedSession, setDismissedSession] = useState<string | null>(null)

  if (!session || session.state === 'idle') return null
  if (session.state === 'error') {
    if (dismissedSession === session.session_id) return null
    const dismiss = () => {
      const banner = `teleop failed: ${session.error ?? 'unknown error'}`
      const app = useAppStore.getState()
      if (app.error === banner) app.setError(null)
      setDismissedSession(session.session_id)
      void api.teleopStop().catch(() => undefined) // clears the sticky error
    }
    return (
      <div className="transport-bar error">
        <span className="transport-kind">teleop</span>
        <span className="transport-detail">{session.error ?? 'failed'}</span>
        <div className="transport-controls">
          <button className="btn btn-secondary" title="dismiss" onClick={dismiss}>
            ✕
          </button>
        </div>
      </div>
    )
  }

  const engaged = session.state === 'engaged'
  const lost = session.tracking === 'lost'

  return (
    <div className={`transport-bar${engaged ? ' teleop-engaged' : ''}`}>
      <span className="transport-kind">◉ teleop</span>
      <TeleopStateBadge session={session} />
      {session.source && (
        <span className="transport-detail">{session.source}</span>
      )}
      {session.state !== 'starting' && (
        <>
          <TrackingDot session={session} />
          <span className="transport-detail">
            {session.stats.target_hz != null
              ? `${session.stats.target_hz.toFixed(0)} Hz`
              : '—'}
            {engaged && lost ? ' · tracking lost — holding last pose' : ''}
          </span>
          {session.notice && (
            <span
              className="transport-detail"
              style={{ color: 'var(--warn)' }}
            >
              ⚠ {session.notice}
            </span>
          )}
        </>
      )}
      <div className="transport-controls">
        {session.state === 'preview' && (
          <button
            className="btn btn-danger"
            disabled={!engageGate.allowed}
            title={engageGate.reason ?? 'take control of the hand'}
            onClick={() => void api.teleopEngage().catch(fail)}
          >
            ⚡ engage
          </button>
        )}
        {engaged && (
          <button
            className="btn btn-secondary"
            title="release control — hand holds its pose"
            onClick={() => void api.teleopDisengage().catch(fail)}
          >
            disengage
          </button>
        )}
        <button
          className={`btn ${engaged ? 'btn-danger' : 'btn-secondary'}`}
          title="end the teleop session"
          onClick={() => void api.teleopStop().catch(fail)}
        >
          ■ stop
        </button>
      </div>
    </div>
  )
}

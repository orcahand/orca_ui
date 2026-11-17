// App session strip, under the header on every tab while an app session is
// live, so Engage / Disengage / Stop are always in reach. Stacks under the
// operation bar: an app in preview and a running operation may coexist; the
// arbiter never lets both own the hand.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useEngageGate } from '../../state/appGate'
import { useAppSessionStore } from '../../state/appSessionStore'
import { useAppStore } from '../../state/appStore'
import { disengage, engage, stop } from './actions'
import { AppStateBadge, TargetRate, TrackingDot } from './badges'

export function SessionBar() {
  const session = useAppSessionStore((s) => s.session)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const setView = useAppStore((s) => s.setView)
  const engageGate = useEngageGate()
  const gate = engageGate.allowed ? null : engageGate.reason
  const [dismissedSession, setDismissedSession] = useState<string | null>(null)

  if (!session || session.state === 'idle') return null
  const name = session.title ?? 'app'

  if (session.state === 'error') {
    if (dismissedSession === session.session_id) return null
    const dismiss = () => {
      const banner = `${name} failed: ${session.error ?? 'unknown error'}`
      const app = useAppStore.getState()
      if (app.error === banner) app.setError(null)
      setDismissedSession(session.session_id)
      void api.appStop(session.session_id).catch(() => undefined) // clears the error
    }
    return (
      <div className="transport-bar error">
        <span className="transport-kind">{name}</span>
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
  const live = session.state === 'preview' || engaged

  return (
    <div className={`transport-bar${engaged ? ' app-engaged' : ''}`}>
      <button
        className="transport-kind app-bar-link"
        title={`open the ${name} tab`}
        onClick={() => session.app && setView(session.app)}
      >
        ◉ {name}
      </button>
      <AppStateBadge session={session} />
      {!wsConnected && (
        <span className="transport-detail" style={{ color: 'var(--warn)' }}>
          offline — the console isn't reachable
        </span>
      )}
      {live && (
        <>
          <TrackingDot session={session} />
          <span className="transport-detail">
            <TargetRate session={session} />
            {engaged && session.tracking === 'lost' ? ' · holding the pose' : ''}
          </span>
        </>
      )}
      {session.notice && (
        <span className="transport-detail" style={{ color: 'var(--warn)' }}>
          ⚠ {session.notice}
        </span>
      )}
      <div className="transport-controls">
        {session.state === 'preview' && (
          <>
            {gate && <span className="transport-detail">{gate}</span>}
            <button
              className="btn btn-danger"
              disabled={gate !== null}
              title={gate ?? 'the hand follows the app, ramping in from where it is'}
              onClick={() => engage(session)}
            >
              ⚡ engage
            </button>
          </>
        )}
        {engaged && (
          <button
            className="btn btn-secondary"
            title="back to preview — the hand holds its pose"
            onClick={() => disengage(session)}
          >
            disengage
          </button>
        )}
        {session.state !== 'stopping' && (
          <button
            className={`btn ${engaged ? 'btn-danger' : 'btn-secondary'}`}
            title={
              engaged
                ? 'end the app — torque goes off where the hand is'
                : 'end the app'
            }
            onClick={() => stop(session)}
          >
            ■ stop
          </button>
        )}
      </div>
    </div>
  )
}

// Slim dashboard presence for a live teleop session; the transport bar is
// the primary control surface, this is read-mostly + a jump to the tab.

import { useAppStore } from '../../state/appStore'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'
import { Panel } from '../common/Panel'
import { TeleopStateBadge, TrackingDot } from './SessionCard'

export function TeleopStatusCard() {
  const session = useTeleopStore((s) => s.session)
  const setView = useAppStore((s) => s.setView)

  if (!isTeleopActive(session) || !session) return null

  return (
    <Panel
      title="Teleop"
      toolbar={
        <button className="btn btn-secondary" onClick={() => setView('teleop')}>
          configure →
        </button>
      }
    >
      <div className="setup-card-row" style={{ fontSize: 10 }}>
        <TeleopStateBadge session={session} />
        <span className="setup-card-detail">{session.source}</span>
        <TrackingDot session={session} />
        <span className="setup-card-detail">
          {session.stats.target_hz != null
            ? `${session.stats.target_hz.toFixed(0)} Hz`
            : 'no targets yet'}
        </span>
      </div>
    </Panel>
  )
}

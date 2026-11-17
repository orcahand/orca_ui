// Small read-outs shared by the session bar and the session panel.

import type { AppSnapshot } from '../../api/types'

export function AppStateBadge({ session }: { session: AppSnapshot }) {
  const label =
    session.state === 'engaged' && session.ramping ? 'engaging' : session.state
  return <span className={`app-state-badge ${session.state}`}>{label}</span>
}

export function TrackingDot({ session }: { session: AppSnapshot }) {
  const lost = session.tracking === 'lost'
  return (
    <span
      className={`tracking-dot${lost ? ' lost' : ''}`}
      title={lost ? 'no fresh targets — holding the pose' : 'targets arriving'}
    />
  )
}

export function TargetRate({ session }: { session: AppSnapshot }) {
  const hz = session.stats.target_hz
  return <>{hz != null ? `${hz.toFixed(0)} Hz` : '—'}</>
}

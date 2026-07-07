import { useAppStore } from '../../state/appStore'
import type { HandState } from '../../api/types'
import { TOPICS } from '../../api/types'

const STATE_CLASS: Record<HandState, string> = {
  connected: 'connected',
  degraded: 'busy',
  detecting: 'busy',
  connecting: 'busy',
  reconnecting: 'busy',
  disconnected: 'disconnected',
}

const STATE_LABEL: Record<HandState, string> = {
  connected: 'Connected',
  degraded: 'Degraded',
  detecting: 'Detecting…',
  connecting: 'Connecting…',
  reconnecting: 'Reconnecting…',
  disconnected: 'Disconnected',
}

export function AppHeader() {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const view = useAppStore((s) => s.view)
  const setView = useAppStore((s) => s.setView)
  const rates = useAppStore((s) => s.rates)

  const state: HandState = !wsConnected
    ? 'disconnected'
    : (status?.state ?? 'detecting')
  const caps = status?.capabilities

  const measuredHz = rates[TOPICS.jointsMeasured] ?? 0
  const taxelHz = rates[TOPICS.tactileTaxels] ?? 0

  return (
    <header>
      <h1>ORCA HAND</h1>
      {handInfo && (
        <span className="capability-badge">
          {handInfo.model_name}
          {handInfo.mock ? ' · MOCK' : ''}
        </span>
      )}
      <span className={`status-indicator ${STATE_CLASS[state]}`}>
        {wsConnected ? STATE_LABEL[state] : 'Backend offline'}
      </span>
      {caps && (
        <>
          <span className={`capability-badge ${caps.motors ? 'on' : ''}`}>
            MOTORS
          </span>
          <span className={`capability-badge ${caps.tactile ? 'on' : ''}`}>
            TACTILE
          </span>
          <span className={`capability-badge ${caps.encoders ? 'on' : ''}`}>
            ENCODERS
          </span>
          {caps.degraded && <span className="capability-badge warn">DEGRADED</span>}
        </>
      )}
      <span className="rate-meters">
        {measuredHz > 0 && `joints ${measuredHz}Hz`}
        {measuredHz > 0 && taxelHz > 0 && ' · '}
        {taxelHz > 0 && `taxels ${taxelHz}Hz`}
      </span>
      <div className="header-spacer" />
      <nav className="view-tabs">
        <button
          className={`view-tab ${view === 'dashboard' ? 'active' : ''}`}
          onClick={() => setView('dashboard')}
        >
          Dashboard
        </button>
        <button
          className={`view-tab ${view === '3d' ? 'active' : ''}`}
          onClick={() => setView('3d')}
        >
          3D View
        </button>
      </nav>
    </header>
  )
}

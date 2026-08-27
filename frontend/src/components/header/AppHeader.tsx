// Console header: brand lockup, model badge, status pill, the view tabs,
// and the E-stop hard right. Capability badges + Hz meters live in the
// Motors tab. The 3D scene lives on the Dashboard, so there is no 3D tab.

import type { HandState } from '../../api/types'
import type { ViewName } from '../../state/appStore'
import { useAppStore } from '../../state/appStore'
import { EStopButton } from './EStopButton'
import { ThemeToggle } from './ThemeToggle'

const STATE_CLASS: Record<HandState, string> = {
  connected: 'connected',
  degraded: 'busy',
  detecting: 'busy',
  connecting: 'busy',
  reconnecting: 'busy',
  maintenance: 'maintenance',
  disconnected: 'disconnected',
}

const STATE_LABEL: Record<HandState, string> = {
  connected: 'Connected',
  degraded: 'Degraded',
  detecting: 'Detecting…',
  connecting: 'Connecting…',
  reconnecting: 'Reconnecting…',
  maintenance: 'Maintenance',
  disconnected: 'Disconnected',
}

const TABS: { id: ViewName; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'poses', label: 'Poses' },
  { id: 'teleop', label: 'Teleop' },
  { id: 'setup', label: 'Setup' },
  { id: 'motors', label: 'Motors' },
  { id: 'stats', label: 'Stats' },
]

export function AppHeader() {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const view = useAppStore((s) => s.view)
  const setView = useAppStore((s) => s.setView)

  const state: HandState = !wsConnected
    ? 'disconnected'
    : (status?.state ?? 'detecting')
  // Defensive: a backend state this build doesn't know yet must still render
  // a legible pill, not a blank one.
  const pillClass: string = STATE_CLASS[state] ?? 'busy'
  const pillLabel: string = STATE_LABEL[state] ?? state

  return (
    <header>
      <h1 className="brand">
        <span className="brand-mark">◈ ORCA</span>
        <span className="brand-sub">HAND CONSOLE</span>
      </h1>
      {handInfo && (
        <span className="capability-badge">
          {handInfo.model_name}
          {handInfo.mock ? ' · MOCK' : ''}
        </span>
      )}
      {handInfo?.core?.development && (
        // Only shown off a release: on a dev build the hand's behaviour may
        // not match any shipped version, and that should never be a surprise.
        <span className="capability-badge dev-build" title={handInfo.core.summary}>
          DEV CORE
          {handInfo.core.branch ? ` · ${handInfo.core.branch}` : ''}
          {handInfo.core.dirty ? ' *' : ''}
        </span>
      )}
      <span className={`status-indicator ${pillClass}`}>
        {wsConnected ? pillLabel : 'Backend offline'}
      </span>
      <div className="header-spacer" />
      <nav className="view-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`view-tab ${view === tab.id ? 'active' : ''}`}
            onClick={() => setView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <ThemeToggle />
      <EStopButton />
    </header>
  )
}

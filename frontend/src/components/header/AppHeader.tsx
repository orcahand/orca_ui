// Console header: brand lockup, model picker, status pill, the link controls
// (disconnect / reconnect), the view tabs, and the E-stop hard right.
// Capability badges + Hz meters live in the Motors tab.

import type { HandState } from '../../api/types'
import type { ViewName } from '../../state/appStore'
import { useAppStore } from '../../state/appStore'
import { BoardPicker } from './BoardPicker'
import { EStopButton } from './EStopButton'
import { LinkControls } from './LinkControls'
import { ModelPicker } from './ModelPicker'
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
  { id: '3d', label: '3D' },
  { id: 'poses', label: 'Poses' },
  { id: 'teleop', label: 'Teleop' },
  { id: 'setup', label: 'Setup' },
  { id: 'motors', label: 'Motors' },
]

export function AppHeader() {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const view = useAppStore((s) => s.view)
  const setView = useAppStore((s) => s.setView)

  // Every tab is offered for every hand: the dashboard's own sections are
  // capability-gated one level down, so a motors-only hand gets a shorter
  // page rather than no page. Bare motor mode is the exception — there is no
  // hand to pose, no pose library worth keeping and nothing to calibrate, so
  // only the two tabs that act on motors are offered.
  const bare = status?.bare ?? false
  const tabs = bare
    ? TABS.filter((tab) => tab.id === 'dashboard' || tab.id === 'motors')
    : TABS

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
      <ModelPicker />
      <BoardPicker />
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
      <LinkControls />
      <div className="header-spacer" />
      <nav className="view-tabs">
        {tabs.map((tab) => (
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

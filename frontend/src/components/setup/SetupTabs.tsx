// Sub-tabs of Setup: the hand's own setup flow, and visual calibration (its
// own page, reachable without a connected hand).

import { useAppStore, type ViewName } from '../../state/appStore'

const TABS: { id: ViewName; label: string }[] = [
  { id: 'setup', label: 'Hand setup' },
  { id: 'visual-calibration', label: 'Visual calibration' },
]

export function SetupTabs() {
  const view = useAppStore((s) => s.view)
  const setView = useAppStore((s) => s.setView)
  return (
    <nav className="view-tabs setup-tabs">
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
  )
}

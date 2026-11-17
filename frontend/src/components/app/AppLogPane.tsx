// The app session's log: the app's own output and log messages, and session
// events (cumulative app.log topic, merged in appSessionStore).

import { useAppSessionStore } from '../../state/appSessionStore'
import { LogPane } from '../common/LogPane'

export function AppLogPane() {
  const lines = useAppSessionStore((s) => s.logLines)
  return (
    <LogPane
      title="Log"
      lines={lines}
      emptyText="nothing yet — the app's output and session events land here"
    />
  )
}

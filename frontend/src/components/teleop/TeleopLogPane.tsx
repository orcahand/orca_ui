// Live teleop log: child stdout/stderr, protocol notes, and session events
// (cumulative teleop.log topic, seq-merged in teleopStore).

import { useTeleopStore } from '../../state/teleopStore'
import { LogPane } from '../common/LogPane'

export function TeleopLogPane() {
  const lines = useTeleopStore((s) => s.logLines)
  return (
    <LogPane
      title="Teleop Log"
      lines={lines}
      emptyText="no teleop output yet — streamer startup and session events
          land here"
    />
  )
}

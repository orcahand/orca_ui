// git clone + uv sync output for the orca_teleop checkout (cumulative
// teleop.install.log topic). Its own pane rather than the session log: that
// ring is cleared when a session starts, which would wipe the install record
// at the moment the user acts on it.

import { useTeleopStore } from '../../state/teleopStore'
import { LogPane } from '../common/LogPane'

export function TeleopInstallLogPane() {
  const lines = useTeleopStore((s) => s.installLogLines)
  if (lines.length === 0) return null
  return <LogPane title="Install Log" lines={lines} emptyText="" />
}

// Teleop tab: source picker + session lifecycle + camera preview + log.
// Configuration only — engage/disengage is global (transport bar works from
// every tab); this tab is reachable even before a hand session exists so a
// camera/glove can be tested against the 3D ghost alone.

import { useEffect } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useTeleopStore } from '../../state/teleopStore'
import { CameraPreview } from '../teleop/CameraPreview'
import { InstallCard } from '../teleop/InstallCard'
import { SessionCard } from '../teleop/SessionCard'
import { SourceCard } from '../teleop/SourceCard'
import { TeleopInstallLogPane } from '../teleop/TeleopInstallLogPane'
import { TeleopLogPane } from '../teleop/TeleopLogPane'

export function TeleopView() {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const setSession = useTeleopStore((s) => s.setSession)
  const mergeLog = useTeleopStore((s) => s.mergeLog)
  const sources = useTeleopStore((s) => s.sources)

  // Belt-and-braces resync (the WS snapshot replay is the primary path).
  useEffect(() => {
    if (!wsConnected) return
    api
      .teleopState()
      .then((body) => setSession(body.session))
      .catch(() => undefined)
    api
      .teleopLog()
      .then(mergeLog)
      .catch(() => undefined)
  }, [wsConnected, setSession, mergeLog])

  // The install card leads when there is no usable checkout, but the source
  // and session cards stay: external mode launches the streamer by hand and
  // works without a runner.
  return (
    <>
      {sources !== null && !sources.runner.available && <InstallCard />}
      <div className="setup-grid teleop-grid">
        <SourceCard />
        <SessionCard />
      </div>
      <CameraPreview />
      <TeleopInstallLogPane />
      <TeleopLogPane />
    </>
  )
}

// Teleop tab: source picker + session lifecycle + camera preview + log.
// Configuration only — engage/disengage is global (transport bar works from
// every tab); this tab is reachable even before a hand session exists so a
// camera/glove can be tested against the 3D ghost alone.
//
// Three states: no teleop manager at all (--no-teleop), no orca_teleop
// checkout (install gate), and the normal console. The gate replaces the tab
// rather than sitting above it — controls that can only fail read as broken.

import { useEffect, useState } from 'react'
import { ApiError, api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useTeleopStore } from '../../state/teleopStore'
import { CameraPreview } from '../teleop/CameraPreview'
import { SessionCard } from '../teleop/SessionCard'
import { SourceCard } from '../teleop/SourceCard'
import { TeleopInstallLogPane } from '../teleop/TeleopInstallLogPane'
import { TeleopLogPane } from '../teleop/TeleopLogPane'
import { TeleopUnavailable } from '../teleop/TeleopUnavailable'

export function TeleopView() {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const setSession = useTeleopStore((s) => s.setSession)
  const mergeLog = useTeleopStore((s) => s.mergeLog)
  const sources = useTeleopStore((s) => s.sources)
  const setSources = useTeleopStore((s) => s.setSources)
  const session = useTeleopStore((s) => s.session)
  const setDraft = useTeleopStore((s) => s.setDraft)
  // The gate hides the whole console; this is the escape hatch for a streamer
  // running on another machine, which needs no local checkout.
  const [showExternal, setShowExternal] = useState(false)
  const [disabled, setDisabled] = useState(false)

  // Belt-and-braces resync (the WS snapshot replay is the primary path). The
  // source probe lives here rather than in SourceCard because the gate
  // decision depends on it and SourceCard may never mount.
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
    api
      .teleopSources()
      .then((info) => {
        setSources(info)
        setDisabled(false)
      })
      // 503 here means the console was started with --no-teleop: no manager
      // exists, and no amount of installing changes that.
      .catch((error) => {
        if (error instanceof ApiError && error.status === 503) setDisabled(true)
      })
  }, [wsConnected, setSession, mergeLog, setSources])

  if (disabled) {
    return (
      <div className="teleop-gate">
        <div className="teleop-gate-eyebrow">Teleoperation</div>
        <h2 className="teleop-gate-title">Teleop is switched off</h2>
        <p className="teleop-gate-lede">
          This console was started with <code>--no-teleop</code>, so no teleop
          manager exists in this process. Restart it without that flag to use
          teleoperation.
        </p>
      </div>
    )
  }

  // A live session (external mode, or one started before the checkout moved)
  // always outranks the gate — never hide controls for a running pipeline.
  const gated =
    sources !== null &&
    !sources.runner.available &&
    !showExternal &&
    (session === null || session.state === 'idle')

  if (gated) {
    return (
      <>
        <TeleopUnavailable
          onExternal={() => {
            setDraft({ external: true })
            setShowExternal(true)
          }}
        />
        <TeleopInstallLogPane />
      </>
    )
  }

  return (
    <>
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

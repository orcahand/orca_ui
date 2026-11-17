// One layout for every app tab (Teleop, RL): session and settings on the
// left; the app's pictures and the 3D hand with the app's ghost in the
// centre; the log below. A tab differs only by its app id.

import { useEffect } from 'react'
import { api } from '../../api/rest'
import type { AppId } from '../../api/types'
import { isAppActive, useAppEntry, useAppSessionStore } from '../../state/appSessionStore'
import { useAppStore } from '../../state/appStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { HandScenePanel } from '../three/HandScenePanel'
import { AppLogPane } from './AppLogPane'
import { PictureTiles } from './PictureTiles'
import { SessionPanel } from './SessionPanel'
import { SettingsForm } from './SettingsForm'

export function AppView({ app, withHand }: { app: AppId; withHand: boolean }) {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const entry = useAppEntry(app)
  const session = useAppSessionStore((s) => s.session)
  const mine = session?.app === app ? session : null

  // The session itself comes from the WebSocket (replayed on subscribe); a
  // REST copy could land after a newer push and overwrite it.
  useEffect(() => {
    if (!wsConnected) return
    const store = useAppSessionStore.getState()
    void store.refreshApps()
    api.appLog().then(store.mergeLog).catch(() => undefined)
  }, [wsConnected])

  // The app's own data draws this tab: if it breaks the tab, the header and
  // E-STOP stay.
  return (
    <ErrorBoundary label={`The ${entry?.title ?? app} tab`}>
      <div className="app-view">
        <div className="app-view-side">
          <SessionPanel app={app} entry={entry} />
          <SettingsForm app={app} entry={entry} session={mine} />
        </div>
        <div className="app-view-main">
          {mine && isAppActive(mine) && mine.session_id && (
            <PictureTiles sessionId={mine.session_id} />
          )}
          {withHand ? (
            <HandScenePanel height="min(52vh, 560px)" />
          ) : (
            <p className="setup-card-hint">
              The 3D hand shows once a hand is connected (or with --mock).
            </p>
          )}
        </div>
      </div>
      {mine && <AppLogPane />}
    </ErrorBoundary>
  )
}

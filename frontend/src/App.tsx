import { lazy, Suspense, useEffect } from 'react'
import { api } from './api/rest'
import { startStreamClient } from './api/streamClient'
import { BootHero } from './components/BootHero'
import { ErrorBanner } from './components/common/ErrorBanner'
import { MaintenanceBanner } from './components/common/MaintenanceBanner'
import { AppHeader } from './components/header/AppHeader'
import { DashboardView } from './components/views/DashboardView'
import { MotorsView } from './components/views/MotorsView'
import { PosesView } from './components/views/PosesView'
import { SetupView } from './components/views/SetupView'
import { useAppStore } from './state/appStore'

// three.js only loads when the 3D tab first opens.
const ThreeDView = lazy(() =>
  import('./components/views/ThreeDView').then((m) => ({
    default: m.ThreeDView,
  })),
)

// Pre-session states show the boot hero. Maintenance/reconnecting/degraded
// keep the normal views — a session exists (or existed moments ago).
const BOOT_STATES = new Set(['disconnected', 'detecting', 'connecting'])

export default function App() {
  const view = useAppStore((s) => s.view)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const handState = useAppStore((s) => s.status?.state ?? null)

  useEffect(() => {
    startStreamClient()
    api.status().then(useAppStore.getState().setStatus).catch(() => undefined)
    api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
  }, [])

  const booting =
    !wsConnected || handState === null || BOOT_STATES.has(handState)

  return (
    <div className="container">
      <AppHeader />
      <ErrorBanner />
      {booting ? (
        <BootHero />
      ) : (
        <>
          {(view === 'dashboard' || view === '3d' || view === 'poses') && (
            <MaintenanceBanner />
          )}
          {view === 'dashboard' && <DashboardView />}
          {view === '3d' && (
            <Suspense
              fallback={<div className="detecting-card">loading 3D view…</div>}
            >
              <ThreeDView />
            </Suspense>
          )}
          {view === 'poses' && <PosesView />}
          {view === 'setup' && <SetupView />}
          {view === 'motors' && <MotorsView />}
        </>
      )}
    </div>
  )
}

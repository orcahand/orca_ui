import { useEffect } from 'react'
import { api } from './api/rest'
import { startStreamClient } from './api/streamClient'
import { BootHero } from './components/BootHero'
import { ErrorBanner } from './components/common/ErrorBanner'
import { CalibrationBanner } from './components/common/CalibrationBanner'
import { MaintenanceBanner } from './components/common/MaintenanceBanner'
import { AppHeader } from './components/header/AppHeader'
import { TransportBar } from './components/transport/TransportBar'
import { DashboardView } from './components/views/DashboardView'
import { MotorsView } from './components/views/MotorsView'
import { PosesView } from './components/views/PosesView'
import { SetupView } from './components/views/SetupView'
import { StatsView } from './components/views/StatsView'
import { TeleopView } from './components/views/TeleopView'
import { useAppStore } from './state/appStore'

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
      <TransportBar />
      <ErrorBanner />
      {booting ? (
        // Some tabs stay reachable while the backend is up but no hand
        // session exists: Teleop (test a camera/glove against the 3D ghost),
        // Motors (chain configuration happens at ASSEMBLY time, when there
        // is no connectable hand at all) and Stats (lifetime usage history
        // is persisted — readable with the hand unplugged). Hardware actions
        // remain backend-gated.
        wsConnected &&
        (view === 'teleop' || view === 'motors' || view === 'stats') ? (
          <>
            {view === 'teleop' && <TeleopView />}
            {view === 'motors' && <MotorsView />}
            {view === 'stats' && <StatsView />}
          </>
        ) : (
          <BootHero />
        )
      ) : (
        <>
          {(view === 'dashboard' || view === 'poses') && (
            <>
              <MaintenanceBanner />
              <CalibrationBanner />
            </>
          )}
          {view === 'dashboard' && <DashboardView />}
          {view === 'poses' && <PosesView />}
          {view === 'teleop' && <TeleopView />}
          {view === 'setup' && <SetupView />}
          {view === 'motors' && <MotorsView />}
          {view === 'stats' && <StatsView />}
        </>
      )}
    </div>
  )
}

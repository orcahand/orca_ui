import { lazy, Suspense, useEffect } from 'react'
import { api } from './api/rest'
import { startStreamClient } from './api/streamClient'
import { AppHeader } from './components/header/AppHeader'
import { ErrorBanner } from './components/common/ErrorBanner'
import { DashboardView } from './components/views/DashboardView'
import { useAppStore } from './state/appStore'

// three.js only loads when the 3D tab first opens.
const ThreeDView = lazy(() =>
  import('./components/views/ThreeDView').then((m) => ({
    default: m.ThreeDView,
  })),
)

export default function App() {
  const view = useAppStore((s) => s.view)

  useEffect(() => {
    startStreamClient()
    api.status().then(useAppStore.getState().setStatus).catch(() => undefined)
    api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
  }, [])

  return (
    <div className="container">
      <AppHeader />
      <ErrorBanner />
      {view === 'dashboard' ? (
        <DashboardView />
      ) : (
        <Suspense
          fallback={<div className="detecting-card">loading 3D view…</div>}
        >
          <ThreeDView />
        </Suspense>
      )}
    </div>
  )
}

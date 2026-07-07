import { useEffect } from 'react'
import { api } from './api/rest'
import { startStreamClient } from './api/streamClient'
import { AppHeader } from './components/header/AppHeader'
import { ErrorBanner } from './components/common/ErrorBanner'
import { DashboardView } from './components/views/DashboardView'
import { ThreeDView } from './components/views/ThreeDView'
import { useAppStore } from './state/appStore'

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
      {view === 'dashboard' ? <DashboardView /> : <ThreeDView />}
    </div>
  )
}

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme/theme.css'
// Side-effect import: resolves the stored/OS theme and stamps <html> before
// the first render. index.html does the same synchronously to beat the paint;
// this is what makes the store's state agree with it.
import './theme/themeStore'
import App from './App'
import { ErrorBoundary } from './components/common/ErrorBoundary'

// A window left open across a rebuild asks for code files the build replaced; reload once to pick
// up the new ones (not again within a minute, so a genuinely missing file cannot loop).
window.addEventListener('vite:preloadError', (event) => {
  try {
    const last = Number(sessionStorage.getItem('orca.reloadedForUpdate') ?? 0)
    if (Date.now() - last < 60_000) return
    sessionStorage.setItem('orca.reloadedForUpdate', String(Date.now()))
  } catch {
    return
  }
  event.preventDefault()
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary label="The console">
      <App />
    </ErrorBoundary>
  </StrictMode>,
)

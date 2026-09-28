import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme/theme.css'
// Side-effect import: resolves the stored/OS theme and stamps <html> before
// the first render. index.html does the same synchronously to beat the paint;
// this is what makes the store's state agree with it.
import './theme/themeStore'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

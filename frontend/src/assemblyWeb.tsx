import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme/theme.css'
import './theme/themeStore'
import { AssemblyGuide } from './components/assembly/AssemblyGuide'

// The guide fills the page the console's dialog would otherwise frame.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div style={{ height: '100dvh', overflow: 'hidden', background: 'var(--bg)', color: 'var(--text)' }}>
      <AssemblyGuide onClose={() => {}} />
    </div>
  </StrictMode>,
)

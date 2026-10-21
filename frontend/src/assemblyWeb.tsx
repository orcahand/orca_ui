import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './theme/theme.css'
import './theme/themeStore'
import { AssemblyGuide } from './components/assembly/AssemblyGuide'

// The guide fills the page the console's dialog would otherwise frame. The
// document itself scrolls: the inner scroll panes only exist inside the
// console's .assembly-dialog, so clipping here leaves nothing scrollable.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <div style={{ minHeight: '100dvh', background: 'var(--bg)', color: 'var(--text)' }}>
      <AssemblyGuide onClose={() => {}} />
    </div>
  </StrictMode>,
)

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../theme/theme.css'
import './bench.css'
// Side-effect import: resolves the stored theme before the first render,
// exactly as the console's entry does.
import '../theme/themeStore'
import { BenchApp } from './BenchApp'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BenchApp />
  </StrictMode>,
)

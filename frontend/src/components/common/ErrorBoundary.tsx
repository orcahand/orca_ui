// Catches a render error so the console shows what broke instead of a blank page.
// With `fallback`, a broken part (e.g. a 3D preview) is replaced and the rest keeps working.

import { Component, type ReactNode } from 'react'

// How browsers report a code file that a newer build has replaced.
const STALE_BUILD = /dynamically imported module|Importing a module script failed|error loading dynamically imported/i

export class ErrorBoundary extends Component<
  { label: string; fallback?: (error: Error) => ReactNode; children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: { componentStack?: string | null }) {
    console.error(`[orca-ui] ${this.props.label} crashed`, error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    const stale = STALE_BUILD.test(error.message)
    if (this.props.fallback && !stale) return this.props.fallback(error)
    return (
      <div className="crash-panel" role="alert">
        <div className="crash-title">
          {stale ? 'The console was updated while this window was open' : `${this.props.label} hit an error`}
        </div>
        <pre className="crash-message">{stale ? 'Reload the page to load the new version.' : error.message}</pre>
        <div className="crash-actions">
          <button className="btn btn-secondary" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
      </div>
    )
  }
}

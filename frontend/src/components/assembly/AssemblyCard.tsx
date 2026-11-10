import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { EStopButton } from '../header/EStopButton'
import './assembly-card.css'

const Guide = lazy(() => import('./AssemblyGuide').then((m) => ({ default: m.AssemblyGuide })))
const UpkeepGuide = lazy(() => import('./UpkeepGuide').then((m) => ({ default: m.UpkeepGuide })))
class GuideBoundary extends Component<
  { children: ReactNode; onClose: () => void },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <div className="assembly-loading">
        <EStopButton />
        <p>The guide could not load. Your saved progress is still available.</p>
        <button className="btn" onClick={this.props.onClose}>
          Return to Setup
        </button>
      </div>
    ) : (
      this.props.children
    )
  }
}

function AssemblyPopup({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const node = dialog.current!
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    node.showModal()
    document.body.style.overflow = 'hidden'
    return () => {
      node.close()
      document.body.style.overflow = previousOverflow
      requestAnimationFrame(() => {
        if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
      })
    }
  }, [])
  return createPortal(
    <dialog
      ref={dialog}
      className="assembly-dialog"
      aria-label="Assembly instructions"
      onCancel={(e) => {
        if (e.target === e.currentTarget) {
          e.preventDefault()
          onClose()
        }
      }}
    >
      <GuideBoundary onClose={onClose}>
        <Suspense
          fallback={
            <div className="assembly-loading">
              <EStopButton />
              <p>Opening your assembly guide…</p>
              <button className="btn" onClick={onClose}>
                Close
              </button>
            </div>
          }
        >
          <Guide onClose={onClose} safetyControl={<EStopButton />} />
        </Suspense>
      </GuideBoundary>
    </dialog>,
    document.body,
  )
}
export function AssemblyCard() {
  const [open, setOpen] = useState(false),
    [maintenance, setMaintenance] = useState(false)
  const maintenanceButton = useRef<HTMLButtonElement>(null)
  return (
    <>
      <section className="assembly-launch">
        <div className="assembly-launch-icon" aria-hidden="true">
          ◈
        </div>
        <div className="assembly-launch-copy">
          <span className="assembly-launch-kicker">BUILD · V2.1</span>
          <h2>Assembly instructions</h2>
          <p>
            Build one step at a time with photos, videos and guided checks. Your place is saved
            whenever you leave.
          </p>
        </div>
        <div className="assembly-launch-actions">
          <button type="button" className="btn btn-info" onClick={() => setOpen(true)}>
            Open assembly guide
          </button>
          <button
            type="button"
            ref={maintenanceButton}
            className="btn btn-info"
            aria-expanded={maintenance}
            aria-controls="maintenance"
            onClick={() => setMaintenance((value) => !value)}
          >
            Maintenance
          </button>
        </div>
      </section>
      {maintenance && (
        <GuideBoundary
          onClose={() => {
            setMaintenance(false)
            maintenanceButton.current?.focus()
          }}
        >
          <Suspense fallback={<p role="status">Opening maintenance…</p>}>
            <UpkeepGuide onOpenAssembly={() => setOpen(true)} active={!open} />
          </Suspense>
        </GuideBoundary>
      )}
      {open && <AssemblyPopup onClose={() => setOpen(false)} />}
    </>
  )
}

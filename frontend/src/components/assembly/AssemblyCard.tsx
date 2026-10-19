import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { EStopButton } from '../header/EStopButton'
import { useAppStore } from '../../state/appStore'
import './assembly-card.css'

const Guide = lazy(() => import('./AssemblyGuide').then(m => ({ default: m.AssemblyGuide })))
class GuideBoundary extends Component<{ children: ReactNode; onClose: () => void }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <div className="assembly-loading"><p>The assembly guide could not load. Your saved progress is still available.</p><button className="btn" onClick={this.props.onClose}>Return to Setup</button></div> : this.props.children }
}

function AssemblyPopup({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const control = useAppStore(s => s.control)
  const needsStop = control && (control.torque_enabled || control.control_source !== 'manual')
  useEffect(() => {
    const node = dialog.current!
    const previousOverflow = document.body.style.overflow
    node.showModal()
    document.body.style.overflow = 'hidden'
    return () => { node.close(); document.body.style.overflow = previousOverflow }
  }, [])
  return createPortal(
    <dialog ref={dialog} className="assembly-dialog" aria-label="Assembly instructions" onCancel={e => { if (e.target === e.currentTarget) { e.preventDefault(); onClose() } }}>
      <GuideBoundary onClose={onClose}>
        <Suspense fallback={<div className="assembly-loading"><p>Opening your assembly workspace…</p><button className="btn" onClick={onClose}>Close</button></div>}>
          <Guide onClose={onClose} safetyControl={needsStop ? <EStopButton /> : null} />
        </Suspense>
      </GuideBoundary>
    </dialog>, document.body,
  )
}
export function AssemblyCard() {
  const [open, setOpen] = useState(false)
  const launcher = useRef<HTMLButtonElement>(null)
  function close() { setOpen(false); requestAnimationFrame(() => launcher.current?.focus()) }
  return <>
    <section className="assembly-launch">
      <div className="assembly-launch-icon" aria-hidden="true">◈</div>
      <div className="assembly-launch-copy"><span className="assembly-launch-kicker">BUILD (V2.1)</span><h2>Assembly instructions</h2><p>Build one step at a time with photos, videos and guided checks. Your place is saved whenever you leave.</p></div>
      <button type="button" ref={launcher} className="btn btn-info" onClick={() => setOpen(true)}>Open assembly guide</button>
    </section>
    {open && <AssemblyPopup onClose={close} />}
  </>
}

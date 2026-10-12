// Tensioning for hands without a travel baseline (v2.0, or forced): activate
// the current so the motors hold every tendon taut, then ratchet the spools.
// Nothing is scored. Shown for any running "tension" operation, wherever it
// was started, so the same hand always gets the same steps.

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot } from '../../api/types'
import { isOperationActive, useStartGate } from '../../state/operationStore'
import { EXTRA_DEG, PULL_MORE, useTensionFlow } from '../../state/tensionFlow'
import { failToBanner } from './setupUtils'

type HoldStep = 'activate' | 'ratchet' | 'done'

const STEPS: { key: HoldStep; title: string; note: string }[] = [
  { key: 'activate', title: 'Tension the hand', note: 'motors take up the slack' },
  { key: 'ratchet', title: 'Ratchet the spools', note: 'clockwise until it clicks' },
  { key: 'done', title: 'Done', note: 'torque off' },
]

export function HoldTensionDialog({
  operation,
  onClose,
}: {
  operation: OperationSnapshot | null
  onClose: () => void
}) {
  const gate = useStartGate('motors')
  const wind = useTensionFlow((s) => s.wind)
  const setWind = useTensionFlow((s) => s.setWind)
  const offsetDeg = useTensionFlow((s) => s.offsetDeg)
  const active = operation !== null && isOperationActive(operation)
  const holding = active && operation.state === 'awaiting_input'
  const step: HoldStep = operation === null ? 'activate' : active && holding ? 'ratchet' : active ? 'activate' : 'done'
  const stepIndex = STEPS.findIndex((s) => s.key === step)

  const activate = () =>
    void api.operationStart('tension', { move_motors: wind, offset_deg: offsetDeg }).catch(failToBanner)
  const release = () => void api.operationInput('Release').catch(failToBanner)
  const pulled = (operation?.extra as { pulled_deg?: number } | null)?.pulled_deg ?? null
  // Locked until the pull it asked for has been reported, so a double click pulls once.
  const [pullSentAt, setPullSentAt] = useState<number | null | undefined>(undefined)
  const pulling = pullSentAt !== undefined && pullSentAt === pulled
  const pullMore = () => {
    setPullSentAt(pulled)
    void api.operationInput(PULL_MORE).catch((error) => {
      setPullSentAt(undefined)
      failToBanner(error)
    })
  }
  // A cancelled hold also ends "done", but without a result.
  const released = (operation?.result as { released?: boolean } | null)?.released === true
  const primary = step === 'activate' && !active ? activate : step === 'ratchet' ? release : null

  useEffect(() => {
    if (!primary || (step === 'activate' && gate.blocked)) return
    const onKey = (e: KeyboardEvent) => {
      // A focused button answers Enter itself.
      if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
        e.preventDefault()
        primary()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [primary, step, gate.blocked])

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Tensioning">
      <div className="gt-dialog compact">
        <header className="gt-header">
          <span className="gt-title">Tensioning</span>
          <span className="gt-header-spacer" />
          {active ? (
            <button className="btn btn-secondary" onClick={() => void api.operationStop().catch(failToBanner)}>
              Cancel
            </button>
          ) : (
            <button className="btn btn-secondary" onClick={onClose}>
              Close
            </button>
          )}
        </header>
        <div className="gt-body">
          <nav className="gt-steps">
            {STEPS.map((s, i) => (
              <div
                key={s.key}
                className={`gt-step${i === stepIndex ? ' active' : i < stepIndex ? ' done' : ''}`}
              >
                <span className="gt-step-num">{i < stepIndex ? '✓' : i + 1}</span>
                <span>
                  <div className="gt-step-title">{s.title}</div>
                  <div className="gt-step-note">{s.note}</div>
                </span>
              </div>
            ))}
          </nav>
          <section className="gt-content">
            {step === 'activate' && (
              <div className="gt-pane">
                <h3 className="gt-heading">Tension the hand</h3>
                <p className="setup-copy">
                  {wind
                    ? `Activating the current first winds every finger to its hard stops and back ` +
                      `(the tendons seat), then slowly turns the finger motors ${offsetDeg}° ` +
                      `counterclockwise and holds there, loading the bottom spools.`
                    : `Activating the current makes every finger motor slowly turn ${offsetDeg}° ` +
                      `counterclockwise and hold there, loading the bottom spools. The fingers are not ` +
                      `wound first.`}{' '}
                  Keep fingers clear of the hand while it takes up the slack.
                </p>
                {!active && (
                  <label className="joint-check" title="Drive every finger to its hard stops and back before holding">
                    <input type="checkbox" checked={wind} onChange={(e) => setWind(e.target.checked)} />
                    wind the tendons to the hard stops first
                  </label>
                )}
                {active && (
                  <p className="setup-copy">
                    {operation.phase ?? 'starting'}
                    {operation.detail ? ` — ${operation.detail}` : ''}…
                  </p>
                )}
                {!active && gate.blocked && gate.reason && (
                  <div className="gt-warning">{gate.reason}</div>
                )}
              </div>
            )}
            {step === 'ratchet' && (
              <div className="gt-pane">
                <h3 className="gt-heading">Ratchet the spools</h3>
                <p className="setup-copy">
                  The motors are holding{pulled ? `, turned ${pulled}° counterclockwise` : ''}. Turn each
                  top spool clockwise with the ratchet tool until it clicks, finger by finger. Not
                  enough load on the bottom spools? Pull {EXTRA_DEG}° more. When every spool is
                  tight, release the motors.
                </p>
              </div>
            )}
            {step === 'done' && operation && (
              <div className="gt-pane">
                <h3 className="gt-heading">
                  {operation.state === 'error' ? 'Stopped' : released ? 'Tensioned' : 'Cancelled'}
                </h3>
                <p className="setup-copy">
                  {operation.state === 'error'
                    ? `${operation.error ?? 'the run ended with an error'} — torque is off.`
                    : released
                      ? 'Motors released and torque is off. Calibrate next.'
                      : 'Torque is off. Nothing was recorded.'}
                </p>
              </div>
            )}
            {primary && (
              <div className="gt-actions">
                {step === 'ratchet' && (
                  <button className="btn btn-secondary" disabled={pulling} onClick={pullMore}>
                    Pull {EXTRA_DEG}° more
                  </button>
                )}
                <button
                  className="btn btn-primary"
                  disabled={step === 'activate' && gate.blocked}
                  title={step === 'activate' ? (gate.reason ?? undefined) : undefined}
                  onClick={primary}
                >
                  {step === 'activate' ? 'Activate current' : 'Done — release motors'}
                  <span className="gt-key">↵</span>
                </button>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

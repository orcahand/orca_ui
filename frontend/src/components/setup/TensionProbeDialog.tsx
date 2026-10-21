// Tension probe / tension check dialog. A check first parks with torque off
// and shows the mid-range pose the operator brings the hand to (no joint
// against a stop); then the joints of one kind ramp their current together
// until they move, both directions, every motor driven back to its start in
// between. Every side is scored against the reference breakaway: under 80 %
// still needs the ratchet, over 100 % is tighter than the reference. Done,
// the check offers to open guided tensioning straight at the ratchet with the
// joints still to tension listed.

import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, TensionProbeExtra } from '../../api/types'
import { isOperationActive } from '../../state/operationStore'
import { useSetupVariant } from '../../state/setupVariant'
import { failToBanner } from './setupUtils'
import { compareProbe, usableReference, useProbes } from './ProbeReference'
import { jointsToTension, label, ProbeBody } from './ProbeBody'
import { PosePreview } from './PosePreview'
import { startGuidedTension } from './probeStart'

export { marksFromProbe } from './ProbeBody'

export const POSE_TEXT =
  'Torque is off. Bring every finger to about the middle of its range like the model: nothing bent fully, nothing pressed against a stop, the thumb away from the palm. A tendon that starts against a hard stop would read as tight.'

export function TensionProbeDialog({
  operation,
  onClose,
}: {
  operation: OperationSnapshot
  onClose: () => void
}) {
  const extra = operation.extra as TensionProbeExtra | null
  const active = isOperationActive(operation)
  const plain = useSetupVariant((s) => s.variant !== 'kai')
  const repeats = extra?.repeats ?? 1
  const done = extra?.step === 'done'
  const posing = active && extra?.step === 'pose' && operation.state === 'awaiting_input'
  const { state: probes, refresh } = useProbes(done)
  const method = extra?.methods?.find((m) => m !== 'takeup') ?? 'breakaway'
  const usable = usableReference(probes, method)
  const { name: refName, mismatch } = usable
  const reference = usable.dataset
  const verdict = compareProbe(extra?.results ?? [], reference)
  const isReference = !!extra?.saved && extra.saved === refName
  const setReference = () =>
    void api.probeReference(extra?.saved ?? null).then(refresh).catch(failToBanner)
  const check = extra?.check === true
  const title = check ? 'Tension check' : plain ? 'Breakaway probe' : 'Tension probe'
  const toTension = jointsToTension(verdict)
  const continueTensioning = () =>
    void startGuidedTension({ check_from: extra?.saved, start_at: 'tension' }).catch(failToBanner)
  const posed = () => void api.operationInput('Continue').catch(failToBanner)

  useEffect(() => {
    if (!posing) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
        e.preventDefault()
        posed()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [posing])

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">{title}</span>
          {done && repeats > 1 && <span className="setup-badge">{repeats} passes averaged</span>}
          {done && extra?.saved && <span className="setup-badge manual">saved · {extra.saved}</span>}
          {reference && <span className="setup-badge auto">vs {refName}</span>}
          {probes?.motor_type && <span className="setup-badge">{probes.motor_type}</span>}
          <span className="gt-header-spacer" />
          {done && extra?.saved && (
            <button
              className="btn btn-secondary"
              disabled={isReference}
              title="Keep these currents as what a well-tensioned hand needs; later measurements are compared against them"
              onClick={setReference}
            >
              {isReference ? 'This is the reference' : 'Keep as well-tensioned reference'}
            </button>
          )}
          {active ? (
            <>
              <button className="btn btn-secondary" title="Keeps the run going" onClick={onClose}>
                Hide
              </button>
              <button className="btn btn-secondary" onClick={() => void api.operationStop().catch(failToBanner)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="gt-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          )}
        </header>
        <div className="gt-body single">
          <section className="gt-content">
            {posing ? (
              <>
                <div className="gt-split">
                  <PosePreview caption={<div className="gt-preview-caption">mid-range pose · torque off</div>} />
                  <div className="gt-pane">
                    <h3 className="gt-heading">Bring the hand to this pose first</h3>
                    <p className="setup-copy">{POSE_TEXT}</p>
                    <p className="setup-copy">
                      Continue enables the motors where the hand stands and starts the check: the four fingers of each
                      joint kind move together 40° and back under one current limit, then the other way, then each thumb
                      joint alone; each motor's mean current over the stroke is its reading. Keep clear of the hand from
                      then on.
                    </p>
                  </div>
                </div>
                <div className="gt-actions">
                  <button className="btn btn-primary" onClick={posed}>
                    Continue
                    <span className="gt-key">↵</span>
                  </button>
                </div>
              </>
            ) : (
              <ProbeBody
                extra={extra}
                active={active}
                reference={reference}
                refName={refName}
                mismatch={mismatch}
                heading={
                  <div className="gt-pane">
                    {operation.state === 'error' ? (
                      <>
                        <h3 className="gt-heading">Stopped</h3>
                        <p className="setup-copy">{operation.error ?? 'the run ended with an error'} — torque is off.</p>
                      </>
                    ) : done ? (
                      <h3 className="gt-heading">
                        {!reference
                          ? 'Measurement complete'
                          : toTension.length
                            ? `${toTension.length} tendon${toTension.length === 1 ? '' : 's'} still to tension`
                            : 'Every tendon at or above 90 % of the reference'}
                      </h3>
                    ) : active && extra?.step === 'probing' ? (
                      <h3 className="gt-heading">Probing · keep clear of the hand</h3>
                    ) : (
                      <h3 className="gt-heading">Taking over the hand…</h3>
                    )}
                  </div>
                }
                actions={
                  done && extra?.saved ? (
                    <button
                      className={`btn ${toTension.length ? 'btn-primary' : 'btn-secondary'}`}
                      title={
                        toTension.length
                          ? `Open guided tensioning at the ratchet step with ${toTension.map((t) => label(t.joint)).join(', ')} listed`
                          : 'Open guided tensioning at the ratchet step'
                      }
                      onClick={continueTensioning}
                    >
                      Continue to tensioning
                    </button>
                  ) : null
                }
              />
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

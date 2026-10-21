// Manual calibration: torque stays off and the operator holds each joint on
// its end stop; Enter records the motor position there. The model shows the
// end stop asked for, and the list on the left what has been captured.

import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { ManualCalibrationExtra, ModelMetadata, OperationSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isOperationActive } from '../../state/operationStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { SWEEP_HINT, startTensionSweep } from './probeStart'

const TensionPreview = lazy(() =>
  import('./TensionPreview').then((m) => ({ default: m.TensionPreview })),
)

const RECORD = 'Record'
const DIRECTION_WORD = { flex: 'fully flexed', extend: 'fully extended' } as const

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const label = (joint: string) => joint.replace('_', ' ')
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// "all finger MCPs" for a step that holds a whole group, else the joints by name.
function stepName(joints: string[]): string {
  if (joints.length === 1) return label(joints[0])
  const kind = joints[0].split('_')[1]
  if (joints.every((j) => j.endsWith(`_${kind}`))) {
    return `all finger ${kind === 'abd' ? 'abductions' : `${kind.toUpperCase()}s`}`
  }
  return joints.map(label).join(', ')
}

export function ManualCalibrationDialog({
  operation,
  onClose,
}: {
  operation: OperationSnapshot
  onClose: () => void
}) {
  const handInfo = useAppStore((s) => s.handInfo)
  const [metadata, setMetadata] = useState<ModelMetadata | null>(null)
  useEffect(() => {
    api.modelMetadata().then(setMetadata).catch(fail)
  }, [handInfo?.side])

  const extra = operation.extra as ManualCalibrationExtra | null
  const active = isOperationActive(operation)
  const awaiting = operation.state === 'awaiting_input' ? operation.awaiting : null
  const current = extra?.current ?? null
  // One answer per prompt: the buttons lock until the next hardstop is asked for.
  const promptKey =
    awaiting && current ? `${extra?.prompt_seq ?? 0}:${current.joints.join(',')}:${current.direction}` : null
  const [sentFor, setSentFor] = useState<string | null>(null)
  const sent = promptKey !== null && sentFor === promptKey
  const send = (option: string) => {
    setSentFor(promptKey)
    void api.operationInput(option).catch(fail)
  }

  const finished = !active && operation.state !== 'error' && operation.result != null
  const [moving, setMoving] = useState(false)
  // The hand reconnects after the run, so torque is retried until it is back.
  const moveToZero = async () => {
    setMoving(true)
    try {
      let lastError: unknown = null
      for (let i = 0; i < 40; i++) {
        try {
          await api.torqueEnable()
          lastError = null
          break
        } catch (error) {
          lastError = error
          await sleep(500)
        }
      }
      if (lastError) throw lastError
      await api.jointsZero()
      onClose()
    } catch (error) {
      fail(error)
      setMoving(false)
    }
  }

  useEffect(() => {
    if ((!awaiting || sent) && !(finished && !moving)) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !(e.target instanceof HTMLButtonElement)) {
        e.preventDefault()
        if (awaiting) send(RECORD)
        else void moveToZero()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const asked = useMemo(() => new Set(current?.joints ?? []), [current])
  const overrides = useMemo(() => {
    if (!current) return undefined
    const ends = (handInfo?.joints ?? []).filter((j) => asked.has(j.id))
    return Object.fromEntries(ends.map((j) => [j.id, current.direction === 'flex' ? j.rom[1] : j.rom[0]]))
  }, [handInfo, asked, current])
  const statuses = useMemo(
    () => Object.fromEntries([...asked].map((j) => [j, 'partial' as const])),
    [asked],
  )

  // One row per joint, with the outcome of each of its two end stops.
  const rows = useMemo(() => {
    const out = new Map<string, Partial<Record<'flex' | 'extend', 'recorded' | 'skipped'>>>()
    for (const item of extra?.plan ?? []) if (!out.has(item.joint)) out.set(item.joint, {})
    for (const c of extra?.captured ?? []) if (c.direction) out.get(c.joint)![c.direction] = c.outcome
    return [...out.entries()]
  }, [extra?.plan, extra?.captured])
  const done = extra?.captured.length ?? 0

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Manual calibration">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Manual calibration</span>
          {extra && <span className="setup-badge">{Math.min(done + (active ? 1 : 0), extra.total)} / {extra.total}</span>}
          <span className="gt-header-spacer" />
          {active ? (
            <>
              <button className="btn btn-secondary" title="Keeps the run going" onClick={onClose}>
                Hide
              </button>
              <button className="btn btn-secondary" onClick={() => void api.operationStop().catch(fail)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="gt-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          )}
        </header>
        <div className="gt-body">
          <nav className="gt-steps mc-joints">
            {rows.map(([id, outcome]) => (
              <div key={id} className={`mc-joint${asked.has(id) && active ? ' active' : ''}`}>
                <span>{label(id)}</span>
                {(['flex', 'extend'] as const).map((d) => (
                  <span
                    key={d}
                    className={`mc-mark ${outcome[d] ?? (asked.has(id) && current?.direction === d && active ? 'now' : '')}`}
                    title={`${d}: ${outcome[d] ?? 'to do'}`}
                  >
                    {d === 'flex' ? 'F' : 'E'}
                  </span>
                ))}
              </div>
            ))}
          </nav>
          <section className="gt-content">
            <div className="gt-split">
              {metadata && handInfo ? (
                <ErrorBoundary label="The hand preview" fallback={() => <div className="gt-preview">3D preview unavailable</div>}>
                  <Suspense fallback={<div className="gt-preview">loading model…</div>}>
                    <TensionPreview
                      urdfUrl={metadata.urdf_url}
                      joints={handInfo.joints}
                      mode="still"
                      statuses={statuses}
                      overrides={overrides}
                      blackSkin={handInfo.tactile_skin === true}
                      caption={
                        current && active ? (
                          <div className="mc-caption">
                            <b>{stepName(current.joints)}</b> · {current.direction}
                          </div>
                        ) : null
                      }
                    />
                  </Suspense>
                </ErrorBoundary>
              ) : (
                <div className="gt-preview">loading model…</div>
              )}
              <div className="gt-pane">
                {operation.state === 'error' ? (
                  <>
                    <h3 className="gt-heading">Stopped</h3>
                    <p className="setup-copy">{operation.error ?? 'the run ended with an error'}</p>
                  </>
                ) : !active ? (
                  <>
                    <h3 className="gt-heading">{operation.result ? 'Manual calibration complete' : 'Cancelled'}</h3>
                    <p className="setup-copy">
                      {operation.result
                        ? 'Joints with both end stops recorded are calibrated. Skipped ones keep their previous limits. Press Enter to move the hand to its zero position and close.'
                        : 'Joints whose two end stops were both recorded before the cancel are kept.'}
                    </p>
                  </>
                ) : current ? (
                  <>
                    <h3 className="gt-heading">
                      Hold {stepName(current.joints)} {DIRECTION_WORD[current.direction]}
                    </h3>
                    <p className="setup-copy">
                      {current.joints.length > 1
                        ? `Torque is off. Move these ${current.joints.length} joints together onto their ${current.direction} end stops, like the highlighted joints on the model, and hold them there. Then press Enter once to record every motor position.`
                        : `Torque is off. Move the joint by hand onto its ${current.direction} end stop, like the highlighted joint on the model, and hold it there. Then press Enter to record the motor position.`}
                    </p>
                    {current.joints.map((j) => {
                      const now = extra?.position_deg[j]
                      const from = extra?.start_deg[j]
                      const moved = now != null && from != null ? now - from : null
                      return (
                        <div key={j} className="mc-live">
                          <span>
                            {current.joints.length > 1 ? `${label(j)} · ` : ''}motor {current.motors[j]}
                          </span>
                          <b>{now != null ? `${now.toFixed(1)}°` : '—'}</b>
                          {moved != null && <span>moved {moved >= 0 ? '+' : ''}{moved.toFixed(1)}°</span>}
                        </div>
                      )
                    })}
                  </>
                ) : (
                  <h3 className="gt-heading">Taking over the hand…</h3>
                )}
              </div>
            </div>
            {awaiting && (
              <div className="gt-actions">
                {awaiting.options
                  .filter((o) => o !== RECORD)
                  .map((option) => (
                    <button key={option} className="btn btn-secondary" disabled={sent} onClick={() => send(option)}>
                      {option}
                    </button>
                  ))}
                <button className="btn btn-primary" disabled={sent} onClick={() => send(RECORD)}>
                  Record <span className="gt-key">↵</span>
                </button>
              </div>
            )}
            {finished && (
              <div className="gt-actions">
                <button className="btn btn-primary" disabled={moving} onClick={() => void moveToZero()}>
                  {moving ? 'Moving to zero…' : 'Move to zero'} <span className="gt-key">↵</span>
                </button>
                {operation.result && (
                  <button
                    className="btn btn-secondary"
                    disabled={moving}
                    title={SWEEP_HINT}
                    onClick={() => void startTensionSweep().catch(fail)}
                  >
                    Tension sweep
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

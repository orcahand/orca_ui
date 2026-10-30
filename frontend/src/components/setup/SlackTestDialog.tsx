// Slack test: one joint at a time, the operator holds the finger so the joint
// cannot move while its motor winds each way at low current. Everything the
// spool turns is slack, shown with the ratchet clicks that take it up (rounded
// down, at most five a round); more than half a turn fails the joint and blocks
// calibration until the hand is tensioned and tested again. After the last
// joint the run waits on a review (Back tests it again); Close and On to
// tensioning finish it. On to tensioning opens guided tensioning at the
// ratchet with these clicks on a v2.1 hand, and on any other hand holds the
// motors for simple tensioning with the clicks listed. The tower shows the
// spools the way guided tensioning does.

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, SlackJoint, SlackStatus, SlackTestExtra, SpreadStatus } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isOperationActive } from '../../state/operationStore'
import { isV21Family, useTensionFlow } from '../../state/tensionFlow'
import { failToBanner } from './setupUtils'
import { RunProgress } from './RunProgress'
import { TowerFaces } from './TowerFaces'
import type { SpoolMark } from './TowerPreview'
import { startAfter, startGuidedTension, startHoldTension } from './probeStart'

const label = (joint: string) => joint.replace('_', ' ')
const deg = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}°`)
const SPOOL: Record<SlackStatus, SpreadStatus> = { pass: 'pass', fail: 'slack', skipped: 'unscored' }
const WORD: Record<SlackStatus, string> = { pass: 'pass', fail: 'too slack', skipped: 'skipped' }
const VERDICT: Record<SlackStatus, string> = { pass: 'ok', fail: 'over', skipped: 'none' }
const clicks = (n: number | null | undefined) => (n == null ? '·' : n === 0 ? 'none' : `~${n}`)
// Mirrors SLACK_MAX_CLICKS in orca_ui/hand/reference.py.
const MAX_CLICKS = 5

export function marksFromSlack(results: Record<string, SlackJoint>, joint: string | null, live: number | null): SpoolMark[] {
  return Object.entries(results).map(([j, r]) => ({
    joint: j,
    motor: r.motor ?? 0,
    status: r.status ? SPOOL[r.status] : j === joint ? 'unconfirmed' : 'unscored',
    fraction: null,
    tag: r.status ? `${(r.total_deg ?? 0).toFixed(0)}°` : j === joint && live != null ? `${live.toFixed(0)}°` : '…',
  }))
}

export function SlackTestDialog({ operation, onClose }: { operation: OperationSnapshot; onClose: () => void }) {
  const extra = operation.extra as SlackTestExtra | null
  const active = isOperationActive(operation)
  const results = extra?.results ?? {}
  const joint = extra?.joint ?? null
  const live = extra?.live ?? null
  const awaiting = active && operation.state === 'awaiting_input'
  const holding = awaiting && extra?.step === 'hold'
  const reviewing = awaiting && extra?.step === 'review'
  const finished = reviewing || extra?.step === 'done'
  const testing = active && extra?.step === 'testing' && joint != null
  const rows = Object.entries(results)
  const tested = rows.filter(([, r]) => r.status != null).length
  const failed = rows.filter(([, r]) => r.status === 'fail').map(([j]) => j)
  const current = extra?.settings?.current_ma
  const perClick = extra?.deg_per_click ?? null
  const failedClicks = failed.map((j) => `${label(j)}${results[j].clicks ? ` ~${results[j].clicks} clicks` : ''}`)
  // One answer per prompt: the buttons lock until the next prompt arrives.
  const promptKey = awaiting ? [extra?.step, joint, tested].join('|') : null
  const [sentFor, setSentFor] = useState<string | null>(null)
  useEffect(() => {
    if (!awaiting) setSentFor(null)
  }, [awaiting])
  const [leaving, setLeaving] = useState(false)
  const locked = promptKey === null || sentFor === promptKey || leaving
  const answer = (value: string) => {
    setSentFor(promptKey)
    void api.operationInput(value).catch((error) => {
      setSentFor(null)
      failToBanner(error)
    })
  }
  const finish = () => (reviewing ? api.operationInput('Finish') : Promise.resolve())
  const close = () => {
    setLeaving(true)
    void finish().catch(failToBanner).finally(onClose)
  }
  const isV21 = isV21Family(useAppStore((s) => s.status?.hardware_version ?? null))
  const setHoldClicks = useTensionFlow((s) => s.setHoldClicks)
  const withClicks = rows.filter(([, r]) => (r.clicks ?? 0) > 0)
  const next = () => {
    if (isV21) {
      const ratchet = Object.fromEntries(withClicks.map(([j, r]) => [j, { pct: null, clicks: r.clicks }]))
      return startGuidedTension({ start_at: 'tension', ratchet_joints: ratchet })
    }
    setHoldClicks(Object.fromEntries(withClicks.map(([j, r]) => [j, r.clicks!])))
    return startHoldTension()
  }
  const toTensioning = () => {
    setLeaving(true)
    void finish()
      .then(() => startAfter(operation.run_id, next))
      .catch((error) => {
        setLeaving(false)
        failToBanner(error)
      })
  }

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Slack test">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Slack test</span>
          {active && joint && <span className="setup-badge">{label(joint)}</span>}
          {current != null && <span className="setup-badge auto">{current} mA</span>}
          <span className="gt-header-spacer" />
          {active && !reviewing ? (
            <>
              <button className="btn btn-secondary" title="Keeps the run going" onClick={onClose}>
                Hide
              </button>
              <button
                className="btn btn-secondary"
                title="Stop the run and close"
                onClick={() => {
                  void api.operationStop().catch(failToBanner)
                  onClose()
                }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button className="gt-close" aria-label="Close" title="Close" disabled={leaving} onClick={close}>
              ✕
            </button>
          )}
        </header>
        <div className="gt-body single">
          <section className="gt-content gt-slack">
            {rows.length > 0 && (
              <RunProgress done={tested} total={rows.length} label={active && joint ? label(joint) : undefined} />
            )}
            {operation.state === 'error' ? (
              <div className="gt-pane">
                <h3 className="gt-heading">Stopped</h3>
                <p className="setup-copy">{operation.error ?? 'the run ended with an error'} — torque is off.</p>
              </div>
            ) : finished ? (
              <div className="gt-pane">
                <h3 className="gt-heading">
                  {failed.length
                    ? `Too much slack on ${failed.length} joint${failed.length === 1 ? '' : 's'} — calibration blocked`
                    : 'Every joint is within half a turn'}
                </h3>
                {failed.length > 0 && (
                  <div className="gt-warning slack-advice">
                    <b>Tension {failed.map(label).join(', ')} by hand first.</b> Remove the top spool from the
                    assembly and attach it back on with more pretension, as the assembly manual describes — taking
                    up this much slack with the ratchet wears it. Then run the slack test again.
                  </div>
                )}
                <p className="setup-copy">
                  {failed.length
                    ? `${failedClicks.join(', ')}: the spool turned more than half a turn before the tendons went taut.`
                    : 'Passed. The click counts are what the ratchet takes up of each joint’s slack, rounded down; go on to tensioning.'}{' '}
                  {perClick == null && 'The degrees one click takes up are not set yet, so no click counts are shown. '}
                  {reviewing ? 'Back tests the last joint again. ' : ''}Torque is off.
                </p>
                <div className="gt-actions">
                  {reviewing && (
                    <button
                      className="btn btn-secondary"
                      disabled={locked}
                      title="Discard the last joint's result and test it again"
                      onClick={() => answer('Back')}
                    >
                      Back
                    </button>
                  )}
                  <button className="btn btn-secondary" disabled={leaving} onClick={close}>
                    Close
                  </button>
                  <button
                    className="btn btn-primary"
                    disabled={leaving}
                    title={isV21 ? 'Guided tensioning at the ratchet step, with these clicks' : 'Simple tensioning: the motors hold while you ratchet, with these clicks listed'}
                    onClick={toTensioning}
                  >
                    On to tensioning
                  </button>
                </div>
              </div>
            ) : (
              <div className="gt-pane">
                <h3 className="gt-heading">
                  {holding && joint
                    ? `Hold ${label(joint)}`
                    : testing
                      ? `Testing ${label(joint!)}${extra?.direction != null ? ` · winding ${extra.direction > 0 ? 'positive' : 'negative'}` : ''}`
                      : 'Taking over the hand…'}
                </h3>
                {/* Both texts share one cell, so the dialog keeps its height when Test swaps them. */}
                <div className="slack-copy">
                  <p className={`setup-copy${holding ? '' : ' slack-copy-off'}`} aria-hidden={!holding}>
                    Hold the finger so {joint ? label(joint) : 'the joint'} cannot move, then press Test. Motor{' '}
                    {(joint && results[joint]?.motor) ?? '?'} winds each way at {current ?? '…'} mA until the tendons
                    go taut; keep holding until the next joint is shown.
                  </p>
                  <p className={`setup-copy${holding ? ' slack-copy-off' : ''}`} aria-hidden={holding}>
                    {testing ? 'Keep holding the joint still.' : ''}
                  </p>
                </div>
                <div className="gt-actions">
                  <button
                    className="btn btn-secondary"
                    disabled={!holding || locked || !extra?.can_back}
                    title={extra?.can_back ? "Discard the previous joint's result and test it again" : 'the first joint has no previous one'}
                    onClick={() => answer('Back')}
                  >
                    Back
                  </button>
                  <button className="btn btn-secondary" disabled={!holding || locked} onClick={() => answer('Skip')}>
                    Skip
                  </button>
                  <button className="btn btn-primary" disabled={!holding || locked} onClick={() => answer('Test')}>
                    Test
                  </button>
                </div>
              </div>
            )}
            {rows.length > 0 && (
              <TowerFaces
                marks={marksFromSlack(results, active ? joint : null, live)}
                joints={rows.map(([j]) => j)}
                head={['positive', 'negative', 'total', 'clicks', '']}
                columns="1fr 1fr 60px 50px 80px"
                activeJoints={new Set(active && joint ? [joint] : [])}
                row={(j) => {
                  const r = results[j]
                  const running = active && j === joint && r.status == null
                  return [
                    <span key="p">
                      {r.plus_deg != null ? deg(r.plus_deg) : running && extra?.direction === 1 ? deg(live) : '·'}
                      {r.plus_sense ? <small> {r.plus_sense}</small> : null}
                    </span>,
                    <span key="m">
                      {r.minus_deg != null ? deg(r.minus_deg) : running && extra?.direction === -1 ? deg(live) : '·'}
                      {r.minus_sense ? <small> {r.minus_sense}</small> : null}
                    </span>,
                    <span key="t" title="the reference hand's slack on this joint">
                      {r.status && r.status !== 'skipped' ? deg(r.total_deg) : '·'}
                      {r.ref_deg != null && <small> / {r.ref_deg.toFixed(0)}°</small>}
                    </span>,
                    <span key="c" title={perClick ? `${perClick}° per click, rounded down, at most ${MAX_CLICKS}` : 'degrees per click not set'}>
                      {clicks(r.clicks)}
                    </span>,
                    <span key="s" className={`probe-verdict ${r.status ? VERDICT[r.status] : 'none'}`}>
                      {r.status ? WORD[r.status] : '·'}
                    </span>,
                  ]
                }}
              />
            )}
            <p className="setup-copy dim">
              Motor degrees each spool turned at {current ?? '…'} mA with its joint held, per direction; total is the
              free rotation between the two tendons going taut. More than half a turn (180°) fails. Clicks: the ratchet
              clicks that take up that slack{perClick ? ` at ${perClick}° each` : ''}, rounded down and at most{' '}
              {MAX_CLICKS} a round — the next slack test lists any still missing.
            </p>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

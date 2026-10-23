// Slack test: one joint at a time, the operator holds the finger so the joint
// cannot move while its motor winds each way at low current. Everything the
// spool turns is slack, shown with the ratchet clicks that take it up (rounded
// down); more than half a turn fails the joint and blocks calibration until
// the hand is tensioned and tested again. The tower shows the spools the way
// guided tensioning does.

import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, SlackJoint, SlackStatus, SlackTestExtra, SpreadStatus } from '../../api/types'
import { isOperationActive } from '../../state/operationStore'
import { failToBanner } from './setupUtils'
import { RunProgress } from './RunProgress'
import { TowerFaces } from './TowerFaces'
import type { SpoolMark } from './TowerPreview'

const label = (joint: string) => joint.replace('_', ' ')
const deg = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}°`)
const SPOOL: Record<SlackStatus, SpreadStatus> = { pass: 'pass', fail: 'slack', skipped: 'unscored' }
const WORD: Record<SlackStatus, string> = { pass: 'pass', fail: 'too slack', skipped: 'skipped' }
const VERDICT: Record<SlackStatus, string> = { pass: 'ok', fail: 'over', skipped: 'none' }
const clicks = (n: number | null | undefined) => (n == null ? '·' : n === 0 ? 'none' : `~${n}`)

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
  const done = extra?.step === 'done'
  const holding = active && extra?.step === 'hold' && operation.state === 'awaiting_input'
  const rows = Object.entries(results)
  const tested = rows.filter(([, r]) => r.status != null).length
  const failed = rows.filter(([, r]) => r.status === 'fail').map(([j]) => j)
  const current = extra?.settings?.current_ma
  const perClick = extra?.deg_per_click ?? null
  const failedClicks = failed.map((j) => `${label(j)}${results[j].clicks ? ` ~${results[j].clicks} clicks` : ''}`)
  const answer = (value: string) => void api.operationInput(value).catch(failToBanner)
  const calibrate = () => void api.operationStart('calibrate', {}).catch(failToBanner)

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Slack test">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Slack test</span>
          {active && joint && <span className="setup-badge">{label(joint)}</span>}
          {current != null && <span className="setup-badge auto">{current} mA</span>}
          <span className="gt-header-spacer" />
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
            {rows.length > 0 && (
              <RunProgress done={tested} total={rows.length} label={active && joint ? label(joint) : undefined} />
            )}
            <div className="gt-pane">
              {operation.state === 'error' ? (
                <>
                  <h3 className="gt-heading">Stopped</h3>
                  <p className="setup-copy">{operation.error ?? 'the run ended with an error'} — torque is off.</p>
                </>
              ) : done ? (
                <>
                  <h3 className="gt-heading">
                    {failed.length
                      ? `Too much slack on ${failed.length} joint${failed.length === 1 ? '' : 's'} — calibration blocked`
                      : 'Every joint is within half a turn'}
                  </h3>
                  <p className="setup-copy">
                    {failed.length
                      ? `${failedClicks.join(', ')}: the spool turned more than half a turn before the tendons went taut. Ratchet that much out, or unmount the top spool and reattach it with more inherent tension as the assembly manual describes, then run the slack test again.`
                      : 'Passed. The click counts are what the ratchet takes up of each joint’s slack, rounded down; go on to tensioning.'}{' '}
                    {perClick == null && 'The degrees one click takes up are not set yet, so no click counts are shown. '}
                    Torque is off.
                  </p>
                  <div className="gt-actions">
                    {!failed.length && (
                      <button className="btn btn-secondary" onClick={calibrate}>
                        Calibrate
                      </button>
                    )}
                    <button className="btn btn-primary" onClick={onClose}>
                      {failed.length ? 'Close' : 'On to tensioning'}
                    </button>
                  </div>
                </>
              ) : holding && joint ? (
                <>
                  <h3 className="gt-heading">Hold {label(joint)}</h3>
                  <p className="setup-copy">
                    Hold the finger so {label(joint)} cannot move, then press Test. Motor{' '}
                    {results[joint]?.motor ?? '?'} winds each way at {current ?? '…'} mA until the tendons go taut;
                    keep holding until the next joint is shown.
                  </p>
                  <div className="gt-actions">
                    {extra?.can_back && (
                      <button
                        className="btn btn-secondary"
                        title="Discard the previous joint's result and test it again"
                        onClick={() => answer('Back')}
                      >
                        Back
                      </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => answer('Skip')}>
                      Skip
                    </button>
                    <button className="btn btn-primary" onClick={() => answer('Test')}>
                      Test
                    </button>
                  </div>
                </>
              ) : extra?.step === 'testing' && joint ? (
                <>
                  <h3 className="gt-heading">
                    Testing {label(joint)}
                    {extra.direction != null ? ` · winding ${extra.direction > 0 ? 'positive' : 'negative'}` : ''}
                  </h3>
                  <p className="setup-copy">Keep holding the joint still.</p>
                </>
              ) : (
                <h3 className="gt-heading">Taking over the hand…</h3>
              )}
            </div>
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
                    <span key="c" title={perClick ? `${perClick}° per click, rounded down` : 'degrees per click not set'}>
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
              clicks that take up that slack{perClick ? ` at ${perClick}° each` : ''}, rounded down.
            </p>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

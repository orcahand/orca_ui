// Slack test: every finger motor winds up to half a turn each way at a current
// too low to move a tensioned joint. A spool that turns is winding up slack;
// the degrees are the slack. One that completes the half turn has nothing
// holding it: calibration is blocked until the hand is tensioned and tested
// again. The tower shows the spools the way guided tensioning does.

import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, SlackJoint, SlackStatus, SlackTestExtra, SpreadStatus } from '../../api/types'
import { isOperationActive } from '../../state/operationStore'
import { failToBanner } from './setupUtils'
import { CHECK_HINT, startTensionCheck } from './probeStart'
import { RunProgress } from './RunProgress'
import { TowerFaces } from './TowerFaces'
import type { SpoolMark } from './TowerPreview'

const label = (joint: string) => joint.replace('_', ' ')
const deg = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}°`)
const SPOOL: Record<SlackStatus, SpreadStatus> = { taut: 'pass', slack: 'partial', unspool: 'slack' }
const WORD: Record<SlackStatus, string> = { taut: 'taut', slack: 'slack', unspool: 'half turn' }

export function marksFromSlack(results: Record<string, SlackJoint>, live: Record<string, number> = {}): SpoolMark[] {
  return Object.entries(results).map(([joint, r]) => ({
    joint,
    motor: r.motor ?? 0,
    status: r.status ? SPOOL[r.status] : 'unscored',
    fraction: null,
    tag: r.status ? `${(r.total_deg ?? 0).toFixed(0)}°` : live[joint] != null ? `${live[joint].toFixed(0)}°` : '…',
  }))
}

export function SlackTestDialog({ operation, onClose }: { operation: OperationSnapshot; onClose: () => void }) {
  const extra = operation.extra as SlackTestExtra | null
  const active = isOperationActive(operation)
  const results = extra?.results ?? {}
  const live = extra?.live ?? {}
  const done = extra?.step === 'done'
  const rows = Object.entries(results)
  const unspool = rows.filter(([, r]) => r.status === 'unspool').map(([j]) => j)
  const slack = rows.filter(([, r]) => r.status === 'slack').map(([j]) => j)
  const current = extra?.settings?.current_ma
  const calibrate = () => void api.operationStart('calibrate', {}).catch(failToBanner)

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Slack test">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Slack test</span>
          {active && extra?.direction != null && (
            <span className="setup-badge">winding {extra.direction > 0 ? 'positive' : 'negative'}</span>
          )}
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
              <RunProgress
                done={done ? 2 : extra?.direction === -1 ? 1 : 0}
                total={2}
                label={active ? (extra?.direction == null ? 'starting' : extra.direction > 0 ? 'winding positive' : 'winding negative') : undefined}
              />
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
                    {unspool.length
                      ? `${unspool.length} spool${unspool.length === 1 ? '' : 's'} turned half a turn — calibration blocked`
                      : slack.length
                        ? `Slack on ${slack.length} joint${slack.length === 1 ? '' : 's'}`
                        : 'Every tendon is taut'}
                  </h3>
                  <p className="setup-copy">
                    {unspool.length
                      ? `${unspool.map(label).join(', ')}: nothing went taut within half a turn, so there is no tension left to ratchet against. Unmount that top spool and reattach it with more inherent tension in the system, as the assembly manual describes, then run the slack test again.`
                      : slack.length
                        ? `Passed. ${slack.map(label).join(', ')} turned freely before a tendon went taut; the degrees are the slack in the spool. Move on to the tension check.`
                        : 'Passed: no spool turned at the test current. Move on to the tension check.'}
                    {' '}Torque is off.
                  </p>
                  <div className="gt-actions">
                    {!unspool.length && (
                      <button className="btn btn-secondary" onClick={calibrate}>
                        Calibrate
                      </button>
                    )}
                    <button
                      className="btn btn-primary"
                      title={CHECK_HINT}
                      onClick={() => void startTensionCheck().catch(failToBanner)}
                    >
                      Tension check
                    </button>
                  </div>
                </>
              ) : extra?.step === 'testing' ? (
                <>
                  <h3 className="gt-heading">
                    Winding {extra.direction == null ? '…' : extra.direction > 0 ? 'positive' : 'negative'}
                  </h3>
                  <p className="setup-copy">
                    Every finger motor aims half a turn away at {current ?? '…'} mA. A spool that turns is taking up
                    slack. Keep clear of the hand.
                  </p>
                </>
              ) : (
                <h3 className="gt-heading">Taking over the hand…</h3>
              )}
            </div>
            {rows.length > 0 && (
              <TowerFaces
                marks={marksFromSlack(results, live)}
                joints={rows.map(([j]) => j)}
                head={['positive', 'negative', 'total', '']}
                columns="1fr 1fr 60px 70px"
                activeJoints={new Set(active ? rows.map(([j]) => j) : [])}
                row={(joint) => {
                  const r = results[joint]
                  return [
                    <span key="p">
                      {r.plus_deg == null ? (active && extra?.direction === 1 ? deg(live[joint] ?? 0) : '·') : deg(r.plus_deg)}
                      {r.plus_sense ? <small> {r.plus_sense}</small> : null}
                      {r.plus_capped ? ' ⚠' : ''}
                    </span>,
                    <span key="m">
                      {r.minus_deg == null ? (active && extra?.direction === -1 ? deg(live[joint] ?? 0) : '·') : deg(r.minus_deg)}
                      {r.minus_sense ? <small> {r.minus_sense}</small> : null}
                      {r.minus_capped ? ' ⚠' : ''}
                    </span>,
                    <span key="t">{deg(r.total_deg)}</span>,
                    <span key="s" className={`probe-verdict ${r.status === 'taut' ? 'ok' : r.status === 'slack' ? 'under' : r.status === 'unspool' ? 'over' : 'none'}`}>
                      {r.status ? WORD[r.status] : '·'}
                    </span>,
                  ]
                }}
              />
            )}
            <p className="setup-copy dim">
              Motor degrees each spool turned at {current ?? '…'} mA before it stalled, per direction; total is the
              free rotation between the two tendons going taut. Under the tolerance counts as taut. "Half turn" means
              it reached the cap without anything going taut.
            </p>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}

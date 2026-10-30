// Tension sweep: the four fingers together per joint kind, then each thumb
// joint, are driven slowly from one calibrated limit to the other and back
// while each motor's current is recorded. The current along the travel splits
// into friction (routing drag, which tension raises) and static load (the
// preload of tendon and skin, what the ratchet changes); both are compared
// with the reference sweep curve by curve, and a joint well below the reference
// gets the ratchet clicks that bring it back (at most three a round). The
// tower marks the spools, the list beside each face carries the numbers, and
// the charts show every joint along its whole travel. With clicks listed, the
// dialog holds the motors (a "tension" run, passed in as `hold`) while the
// operator ratchets the marked spools.

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, SpreadStatus, SweepStatus, SweepVerdict, TensionSweepExtra } from '../../api/types'
import { isOperationActive } from '../../state/operationStore'
import { EXTRA_DEG, PULL_MORE, useTensionFlow } from '../../state/tensionFlow'
import { startHoldTension } from './probeStart'
import { failToBanner } from './setupUtils'
import type { SpoolMark } from './TowerPreview'
import { RunProgress } from './RunProgress'
import { SweepCurve, verdictText } from './SweepCurves'
import { TowerFaces } from './TowerFaces'
import { useSweeps } from './sweepReference'

const label = (joint: string) => joint.replace('_', ' ')
const ma = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)} mA`)
const deg = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}°`)
const SPOOL: Record<SweepStatus, SpreadStatus> = { none: 'unscored', ok: 'pass', slack: 'slack', over: 'unscored', under: 'partial', low: 'low' }

export function marksFromSweep(verdict: SweepVerdict | null, motors: Record<string, number>, joints: string[]): SpoolMark[] {
  return joints.map((joint) => {
    const v = verdict?.joints[joint]
    const status = v?.status ?? 'none'
    return {
      joint,
      motor: motors[joint] ?? 0,
      status: v ? SPOOL[status] : 'unscored',
      fraction: null,
      tag: v?.clicks ? `~${v.clicks} clk` : v && status !== 'none' ? verdictText(v) : '…',
    }
  })
}

export function TensionSweepDialog({
  operation,
  hold = null,
  onClose,
}: {
  operation: OperationSnapshot
  hold?: OperationSnapshot | null
  onClose: () => void
}) {
  const extra = operation.extra as TensionSweepExtra | null
  const active = isOperationActive(operation)
  const current = active ? (extra?.current ?? null) : null
  const live = active ? (extra?.active ?? (current ? [current] : [])) : []
  const activeJoints = new Set(live.map((a) => a.joint))
  const joints = extra?.joints ?? []
  const repeats = extra?.repeats ?? 1
  const verdict = extra?.verdict ?? null
  const done = extra?.step === 'done'
  const progress = extra && extra.total > 0 ? Math.min(extra.index, extra.total) : 0
  const motors: Record<string, number> = {}
  for (const r of extra?.results ?? []) motors[r.joint] = r.motor_id
  for (const a of live) motors[a.joint] = a.motor
  const { state: sweeps, refresh } = useSweeps(done)
  const refName = extra?.reference ?? sweeps?.reference ?? null
  const isReference = !!extra?.saved && extra.saved === sweeps?.reference
  const setReference = () => void api.sweepReference(extra?.saved ?? null).then(refresh).catch(failToBanner)
  const entries = Object.entries(verdict?.joints ?? {})
  const under = entries.filter(([, v]) => v.status === 'under' || v.status === 'low').map(([j]) => j)
  const toClick = entries.filter(([, v]) => (v.clicks ?? 0) > 0)
  const totalClicks = toClick.reduce((n, [, v]) => n + (v.clicks ?? 0), 0)
  const over = entries.filter(([, v]) => v.status === 'over').map(([j]) => j)
  const slack = entries.filter(([, v]) => v.status === 'slack').map(([j]) => j)
  // The chart of one joint, over the whole dialog, opened from its row.
  const [plotJoint, setPlotJoint] = useState<string | null>(null)
  const plotted = plotJoint && verdict?.joints[plotJoint] ? plotJoint : null
  const step = (by: number) => {
    if (!plotted) return
    const i = joints.indexOf(plotted)
    setPlotJoint(joints[(i + by + joints.length) % joints.length])
  }
  // Holding the motors for the listed clicks: asked for, running, or over.
  const setSweepRatchet = useTensionFlow((s) => s.setSweepRatchet)
  const holdAsked = useTensionFlow((s) => s.sweepRatchet?.run_id === operation.run_id)
  const holdActive = hold !== null && isOperationActive(hold)
  const holding = holdActive && hold.state === 'awaiting_input'
  const startHold = () => {
    setSweepRatchet(operation)
    void startHoldTension().catch((error) => {
      setSweepRatchet(null)
      failToBanner(error)
    })
  }
  const pulled = (hold?.extra as { pulled_deg?: number } | null)?.pulled_deg ?? null
  // Locked until the pull it asked for has been reported, so a double click pulls once.
  const [pullSentAt, setPullSentAt] = useState<number | null | undefined>(undefined)
  const [releasing, setReleasing] = useState(false)
  useEffect(() => setReleasing(false), [hold?.run_id])
  const pullMore = () => {
    setPullSentAt(pulled)
    void api.operationInput(PULL_MORE).catch((error) => {
      setPullSentAt(undefined)
      failToBanner(error)
    })
  }
  const release = () => {
    setReleasing(true)
    void api.operationInput('Release').catch((error) => {
      setReleasing(false)
      failToBanner(error)
    })
  }
  const released = (hold?.result as { released?: boolean } | null)?.released === true

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Tension sweep">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Tension sweep</span>
          {current?.run && repeats > 1 && <span className="setup-badge">pass {current.run}/{repeats}</span>}
          {done && extra?.saved && <span className="setup-badge manual">saved · {extra.saved}</span>}
          {refName && <span className="setup-badge auto">vs {refName}</span>}
          <span className="gt-header-spacer" />
          {done && extra?.saved && !holdAsked && (
            <button
              className="btn btn-secondary"
              disabled={isReference}
              title="The curves a well-tensioned hand draws over its travel; later sweeps are compared against them"
              onClick={setReference}
            >
              {isReference ? 'This is the reference' : 'Keep as well-tensioned reference'}
            </button>
          )}
          {holdActive ? (
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
          ) : active ? (
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
            <button className="gt-close" aria-label="Close" title="Close" onClick={onClose}>
              ✕
            </button>
          )}
        </header>
        <div className="gt-body single">
          <section className="gt-content">
            {extra && extra.total > 0 && !done && (
              <RunProgress
                done={extra.done ?? progress}
                total={extra.total}
                label={live.length ? `${live.map((a) => label(a.joint)).join(', ')} ${live[0].sense}` : undefined}
              />
            )}
            <div className="gt-pane">
              {operation.state === 'error' ? (
                <>
                  <h3 className="gt-heading">Stopped</h3>
                  <p className="setup-copy">{operation.error ?? 'the run ended with an error'} — torque is off.</p>
                </>
              ) : done && hold?.state === 'error' ? (
                <>
                  <h3 className="gt-heading">Hold stopped</h3>
                  <p className="setup-copy">{hold.error ?? 'the hold ended with an error'} — torque is off.</p>
                </>
              ) : done && hold && !holdActive ? (
                <>
                  <h3 className="gt-heading">{released ? 'Ratcheted · motors released' : 'Hold cancelled'}</h3>
                  <p className="setup-copy">
                    {released
                      ? 'Torque is off. Each click shifts the spool against its motor: calibrate (Calibrate step), then run the tension sweep again.'
                      : 'Torque is off.'}
                  </p>
                </>
              ) : done && holding ? (
                <>
                  <h3 className="gt-heading">Ratchet the marked spools</h3>
                  <p className="setup-copy">
                    The finger motors are holding{pulled ? `, turned ${pulled}° counterclockwise` : ''}. Turn the top spool
                    of each marked motor clockwise by the clicks shown next to it, and stop early if a tendon feels firm.
                    Not enough load on the bottom spools? Pull {EXTRA_DEG}° more. Then release the motors.
                  </p>
                  <div className="gt-actions">
                    <button
                      className="btn btn-secondary"
                      disabled={releasing || (pullSentAt !== undefined && pullSentAt === pulled)}
                      onClick={pullMore}
                    >
                      Pull {EXTRA_DEG}° more
                    </button>
                    <button className="btn btn-primary" disabled={releasing} onClick={release}>
                      Done — release motors
                    </button>
                  </div>
                </>
              ) : done && (holdAsked || holdActive) ? (
                <>
                  <h3 className="gt-heading">Holding the motors…</h3>
                  <p className="setup-copy">
                    {hold?.phase ?? 'starting'}
                    {hold?.detail ? ` — ${hold.detail}` : ''}… Keep fingers clear while the motors take up the slack.
                  </p>
                </>
              ) : done ? (
                <>
                  <h3 className="gt-heading">
                    {!refName
                      ? 'Sweep complete · no reference for this motor family'
                      : toClick.length
                        ? `${totalClicks} click${totalClicks === 1 ? '' : 's'} on ${toClick.length} spool${toClick.length === 1 ? '' : 's'} still to ratchet`
                        : under.length
                          ? `${under.length} tendon${under.length === 1 ? '' : 's'} a little low · under one click, leave them`
                          : slack.length
                            ? `Nothing to tension · ${slack.map((j) => `${label(j)} slack`).join(', ')}`
                            : `Every tendon well tensioned${over.length ? ` · ${over.length} tighter (grey)` : ''}`}
                  </h3>
                  {toClick.length > 0 && (
                    <div className="gt-actions">
                      <button
                        className="btn btn-primary"
                        title="Every finger motor turns a little counterclockwise and holds while you ratchet the marked spools"
                        onClick={startHold}
                      >
                        Hold &amp; ratchet
                      </button>
                    </div>
                  )}
                </>
              ) : live.length ? (
                <>
                  <h3 className="gt-heading">
                    {live.map((a) => label(a.joint)).join(', ')} · {live[0].sense}
                    {repeats > 1 ? ` · pass ${live[0].run}` : ''}
                  </h3>
                  <div className="probe-live">
                    {live.map((a) => (
                      <div key={a.joint} className="mc-live">
                        <span>M{a.motor} · {label(a.joint)}</span>
                        <b>{deg(a.deg)}</b>
                        <span>{ma(a.current_ma)}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <h3 className="gt-heading">Taking over the hand…</h3>
              )}
            </div>
            {extra?.pose_short && Object.keys(extra.pose_short).length > 0 && (
              <div className="flow-info warn">
                mid-range pose not reached on{' '}
                {Object.entries(extra.pose_short).map(([j, d]) => `${label(j)} (${d}° off)`).join(', ')}
              </div>
            )}
            {joints.length > 0 && (
              <TowerFaces
                marks={marksFromSweep(verdict, motors, joints)}
                joints={joints}
                head={['friction', 'static', refName ? 'vs reference' : '', 'clicks']}
                columns="1fr 1fr 150px 50px"
                activeJoints={activeJoints}
                onSelect={verdict ? (joint) => setPlotJoint(joint) : undefined}
                row={(joint) => {
                  const v = verdict?.joints[joint]
                  return [
                    <span key="f" title="(I flex − I extend) / 2, mean over the travel; the small number is the reference's">
                      {v ? ma(v.friction_ma) : '·'}
                      {v?.ref_friction_ma != null && <small> / {Math.round(v.ref_friction_ma)}</small>}
                    </span>,
                    <span key="s" title="(I flex + I extend) / 2, mean over the travel; the small number is the reference's">
                      {v ? ma(v.static_ma) : '·'}
                      {v?.ref_static_ma != null && <small> / {Math.round(v.ref_static_ma)}</small>}
                    </span>,
                    <span key="v" className={`probe-verdict ${v?.status ?? 'none'}`}>
                      {v && v.status !== 'none' ? verdictText(v) : '·'}
                    </span>,
                    <span key="c" title="ratchet clicks still needed, at most 3 a round">
                      {v?.clicks ? `~${v.clicks}` : v && v.status !== 'none' ? '—' : '·'}
                    </span>,
                  ]
                }}
              />
            )}
            {verdict && joints.length > 0 && (
              <p className="setup-copy dim">
                Some difference from the reference can come from the hands being different rather than the tension, so
                clicks are only suggested well below it, at most 3 a round; a joint that needs no click is well
                tensioned.
              </p>
            )}
          </section>
        </div>
        {plotted && verdict && (
          <div className="sweep-plot-overlay" role="dialog" aria-label={`${label(plotted)} curves`}>
            <header className="gt-header">
              <span className="gt-title">{label(plotted)} · along the travel</span>
              <span className="gt-header-spacer" />
              <button className="btn btn-secondary" onClick={() => step(-1)} title="previous joint">
                ‹
              </button>
              <button className="btn btn-secondary" onClick={() => step(1)} title="next joint">
                ›
              </button>
              <button className="gt-close" aria-label="Close" title="Close" onClick={() => setPlotJoint(null)}>
                ✕
              </button>
            </header>
            <div className="sweep-plot-body">
              <SweepCurve joint={plotted} v={verdict.joints[plotted]} legend />
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

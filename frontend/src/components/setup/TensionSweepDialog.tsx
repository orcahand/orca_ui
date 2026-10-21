// Tension sweep: the four fingers together per joint kind, then each thumb
// joint, are driven slowly from one calibrated limit to the other and back
// while each motor's current is recorded. The current along the travel splits
// into friction (routing drag, which tension raises) and static load (the
// preload of tendon and skin, what the ratchet changes); both are compared
// with the reference sweep curve by curve, and a joint below the reference
// gets the ratchet clicks that bring it back (rounded so it never passes 110 %).
// The tower marks the spools, the list beside each face carries the numbers,
// and the charts show every joint along its whole travel.

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import type { OperationSnapshot, SpreadStatus, SweepJointVerdict, SweepStatus, SweepVerdict, TensionSweepExtra } from '../../api/types'
import { isOperationActive } from '../../state/operationStore'
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
    const share = v?.share != null ? Math.round(v.share * 100) : null
    return {
      joint,
      motor: motors[joint] ?? 0,
      status: v ? SPOOL[status] : 'unscored',
      fraction: null,
      tag: v?.clicks ? `~${v.clicks} clk` : share != null ? `${share}%` : v?.friction_ma != null ? `${Math.round(v.friction_ma)} mA` : '…',
    }
  })
}

function stretchText(v: SweepJointVerdict): string {
  if (!v.stretches.length) return ''
  return v.stretches
    .map((st) => `${st.kind} ${st.diff_ma > 0 ? '+' : ''}${Math.round(st.diff_ma)} mA over ${st.from}–${st.to} %`)
    .join('; ')
}

export function TensionSweepDialog({ operation, onClose }: { operation: OperationSnapshot; onClose: () => void }) {
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

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Tension sweep">
      <div className="gt-dialog">
        <header className="gt-header">
          <span className="gt-title">Tension sweep</span>
          {current?.run && repeats > 1 && <span className="setup-badge">pass {current.run}/{repeats}</span>}
          {done && extra?.saved && <span className="setup-badge manual">saved · {extra.saved}</span>}
          {refName && <span className="setup-badge auto">vs {refName}</span>}
          <span className="gt-header-spacer" />
          {done && extra?.saved && (
            <button
              className="btn btn-secondary"
              disabled={isReference}
              title="The curves a well-tensioned hand draws over its travel; later sweeps are compared against them"
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
              ) : done ? (
                <h3 className="gt-heading">
                  {!refName
                    ? 'Sweep complete · no reference for this motor family'
                    : toClick.length
                      ? `${totalClicks} click${totalClicks === 1 ? '' : 's'} on ${toClick.length} spool${toClick.length === 1 ? '' : 's'} still to ratchet`
                      : under.length
                      ? `${under.length} tendon${under.length === 1 ? '' : 's'} a little low · under one click, leave them`
                      : slack.length
                        ? `Nothing to tension · ${slack.map((j) => `${label(j)} slack`).join(', ')}`
                        : `Every tendon at or above 90 % of the reference${over.length ? ` · ${over.length} tighter (grey)` : ''}`}
                </h3>
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
                    <span key="v" className={`probe-verdict ${v?.status ?? 'none'}`} title={v ? stretchText(v) : undefined}>
                      {v && v.status !== 'none' ? verdictText(v) : '·'}
                    </span>,
                    <span key="c" title="ratchet clicks still needed: only below 40 % of the reference, rounded so the joint never passes 110 %">
                      {v?.clicks ? `~${v.clicks}` : v && v.status !== 'none' ? '—' : '·'}
                    </span>,
                  ]
                }}
              />
            )}
            {verdict && joints.length > 0 && (
              <p className="setup-copy dim">
                Differences of up to 60 % from the reference can come from the hands being different rather than the
                tension. Clicks are only suggested below 40 %; a joint that needs no click is well tensioned.
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

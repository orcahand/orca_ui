// What a breakaway probe or tension check run looks like while it runs and
// once it is done: a status bar, the joints ramping right now, then the two
// tower faces one over the other with the spools of each face listed beside
// it, and under that the tendons still to tension with the clicks each needs
// and the way on to the ratchet. Shared by the probe dialog and the check step
// inside guided tensioning.
//
// Scoring (ProbeReference.BANDS): 90-110 % of the reference is right (green),
// 70-90 % still needs the ratchet (yellow), under 70 % is loose (red), over
// 110 % is tighter than the reference and is left alone (grey).

import { useState, type ReactNode } from 'react'
import type { SpreadStatus, TensionProbeDataset, TensionProbeExtra } from '../../api/types'
import type { SpoolMark } from './TowerPreview'
import { RunProgress } from './RunProgress'
import { TowerFaces } from './TowerFaces'
import {
  breakawayStats,
  clicksFor,
  clicksText,
  compareProbe,
  loadPctPerClick,
  savePctPerClick,
  STATUS_WORD,
  type JointVerdict,
  type ProbeVerdict,
  type Status,
} from './ProbeReference'

// Tower colours: green right, yellow "ratchet this", red loose, grey tighter than the reference.
const SPOOL: Record<Status, SpreadStatus> = { none: 'unscored', ok: 'pass', slack: 'slack', over: 'unscored', under: 'partial', low: 'low' }
const RANK: Record<Status, number> = { none: 0, over: 1, ok: 2, under: 3, slack: 4, low: 5 }

function worstOf(row: ProbeVerdict['joints'][string] | undefined): Status {
  const sides = [row?.flex, row?.extend].filter((v): v is JointVerdict => !!v && v.status !== 'none')
  return sides.reduce<Status>((acc, v) => (RANK[v.status] > RANK[acc] ? v.status : acc), 'none')
}

function meanPct(row: ProbeVerdict['joints'][string] | undefined): number | null {
  const pcts = [row?.flex?.pct, row?.extend?.pct].filter((v): v is number => v != null)
  return pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : null
}

// One mark per joint: the worse of its two sides, tagged with the mean share of the reference.
export function marksFromProbe(verdict: ProbeVerdict, motors: Record<string, number>, joints: string[]): SpoolMark[] {
  return joints.map((joint) => {
    const row = verdict.joints[joint]
    const worst = worstOf(row)
    const pct = meanPct(row)
    return { joint, motor: motors[joint] ?? 0, status: SPOOL[worst], fraction: null, tag: pct != null ? `${Math.round(pct)}%` : worst === 'none' ? '…' : worst }
  })
}

// Joints a check says still need the ratchet (any side yellow or red), loosest first.
export function jointsToTension(verdict: ProbeVerdict): { joint: string; pct: number }[] {
  return Object.entries(verdict.joints)
    .map(([joint, row]) => {
      const under = [row.flex, row.extend].filter((v): v is JointVerdict => !!v && (v.status === 'under' || v.status === 'low'))
      const pct = Math.min(...under.map((v) => v.pct ?? 0))
      return under.length ? { joint, pct } : null
    })
    .filter((v): v is { joint: string; pct: number } => v !== null)
    .sort((a, b) => a.pct - b.pct)
}

export function jointsOver(verdict: ProbeVerdict): string[] {
  return Object.entries(verdict.joints)
    .filter(([, row]) => [row.flex, row.extend].some((v) => v && v.status === 'over'))
    .map(([j]) => j)
}

export const label = (joint: string) => joint.replace('_', ' ')
const deg = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(1)}°`)
const ma = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)} mA`)

export function ProbeBody({
  extra,
  active,
  reference,
  refName,
  mismatch,
  heading,
  actions,
}: {
  extra: TensionProbeExtra | null
  // The run is still going (live cells, progress).
  active: boolean
  reference: TensionProbeDataset | null
  refName: string | null
  mismatch: string | null
  // What to say above the faces; the caller knows the step it is in.
  heading?: ReactNode
  // Sits to the right of the "still to tension" list (the way on to the ratchet).
  actions?: ReactNode
}) {
  const live = active ? (extra?.active ?? (extra?.current ? [extra.current] : [])) : []
  const joints = extra?.joints ?? []
  const results = extra?.results ?? []
  const stats = breakawayStats(results)
  const verdict = compareProbe(results, reference)
  const motors: Record<string, number> = {}
  for (const r of results) motors[r.joint] = r.motor_id
  for (const a of live) motors[a.joint] = a.motor
  const activeJoints = new Set(live.map((a) => a.joint))
  const toTension = jointsToTension(verdict)
  const over = jointsOver(verdict)
  const done = extra?.step === 'done'
  const [pctPerClick, setPctPerClick] = useState(loadPctPerClick)
  const changePctPerClick = (v: number) => {
    if (!Number.isFinite(v) || v < 1 || v > 100) return
    setPctPerClick(v)
    savePctPerClick(v)
  }

  const cells = (joint: string) => {
    const row = verdict.joints[joint]
    const worst = worstOf(row)
    const flex = stats.get(`${joint}/flex/breakaway`)
    const extend = stats.get(`${joint}/extend/breakaway`)
    return [
      <span key="f" title={row?.flex?.hint}>
        {flex?.mean != null ? ma(flex.mean) : flex?.skipped ? 'skip' : '·'}
        {row?.flex?.pct != null && <small> {Math.round(row.flex.pct)}%</small>}
      </span>,
      <span key="e" title={row?.extend?.hint}>
        {extend?.mean != null ? ma(extend.mean) : extend?.skipped ? 'skip' : '·'}
        {row?.extend?.pct != null && <small> {Math.round(row.extend.pct)}%</small>}
      </span>,
      <span key="v" className={`probe-verdict ${worst}`}>
        {STATUS_WORD[worst] || (reference ? '·' : '')}
      </span>,
    ]
  }

  return (
    <>
      {extra && extra.total > 0 && !done && (
        <RunProgress
          done={extra.done ?? Math.min(extra.index, extra.total)}
          total={extra.total}
          label={active && live.length ? `${live.map((a) => label(a.joint)).join(', ')} ${live[0].sense}` : undefined}
        />
      )}
      {heading}
      {active && live.length > 0 && (
        <div className="probe-live">
          {live.map((a) => (
            <div key={a.joint} className="mc-live">
              <span>
                M{a.motor} · {label(a.joint)}
              </span>
              <b>{deg(a.deg)}</b>
              <span>{ma(a.current_ma)}</span>
            </div>
          ))}
        </div>
      )}
      {extra?.pose_short && Object.keys(extra.pose_short).length > 0 && (
        <div className="flow-info warn">
          start pose not reached on{' '}
          {Object.entries(extra.pose_short)
            .map(([j, d]) => `${label(j)} (${d}° off)`)
            .join(', ')}
          {' '}— probed from where they stood; sides near a limit may be skipped
        </div>
      )}
      {mismatch && <div className="flow-info warn">{mismatch} — nothing is scored</div>}
      {joints.length > 0 && (
        <TowerFaces
          marks={marksFromProbe(verdict, motors, joints)}
          joints={joints}
          head={['flex', 'extend', reference ? `vs ${refName}` : '']}
          columns="1fr 1fr 90px"
          row={cells}
          activeJoints={activeJoints}
        />
      )}
      {done && reference && (
        <div className="probe-todo">
          <div className="probe-todo-list">
            <div className="probe-todo-head">
              <span className="gt-todo-title">
                {toTension.length
                  ? `${toTension.length} tendon${toTension.length === 1 ? '' : 's'} still to tension`
                  : 'Nothing to tension'}
              </span>
              {toTension.length > 0 && (
                <label className="flow-field" title="How many percentage points of the reference one ratchet click adds; provisional until the click test sets it">
                  <span>% per click</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    step={1}
                    value={pctPerClick}
                    onChange={(e) => changePctPerClick(Number(e.target.value))}
                  />
                </label>
              )}
            </div>
            {toTension.map((t) => {
              const clicks = clicksFor(t.pct, pctPerClick)
              return (
                <div key={t.joint} className={`gt-todo-row ${t.pct < 70 ? 'low' : 'partial'}`}>
                  <b>M{motors[t.joint] ?? '?'}</b>
                  <span>{label(t.joint)}</span>
                  <span>{Math.round(t.pct)}%</span>
                  <span>{clicksText(clicks)}</span>
                </div>
              )
            })}
            {over.length > 0 && (
              <div className="probe-todo-note">
                tighter than the reference (grey), left alone: {over.map(label).join(', ')}
              </div>
            )}
          </div>
          {actions && <div className="probe-todo-actions">{actions}</div>}
        </div>
      )}
      {done && !reference && !mismatch && (
        <div className="flow-info warn">no reference probe set: nothing is scored, the run is saved for comparison</div>
      )}
    </>
  )
}

// Scoring a tension probe against a saved reference run. The current per joint
// and side as a percentage of the reference: 90-110 % is right (green),
// 70-90 % still needs the ratchet (yellow), under 70 % is loose (red), over
// 110 % is tighter than the reference and is left alone (grey, not ratcheted).
// The check between tensioning rounds errs on the loose side on purpose: the
// sweep after calibration is the exact measurement.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { ProbeResult, TensionProbeDataset, TensionProbes } from '../../api/types'
import { failToBanner } from './setupUtils'

export const BANDS = {
  low: 70, // % of the reference below which a tendon is loose (red)
  under: 90, // ... below which it still needs the ratchet (yellow)
  over: 110, // ... above which it is tighter than the reference (grey, left alone)
  slackDeg: 3, // stalled take-up travel from which it counts as slack
  freeMa: 50, // breakaway below which running to the cap is a free joint, not slack
  asymMa: 40, // flex vs extend breakaway difference that counts as asymmetric
}

export type Status = 'ok' | 'under' | 'low' | 'over' | 'slack' | 'none'

// How many percentage points of the reference one ratchet click adds. From the
// click experiment of 2026-10-21 on the reference hand: one click on seven
// tendons raised the check by +27 to +95 points (median +60) and the sweep's
// friction by +35 to +120 points. The operator can change it in the check dialog.
export const DEFAULT_PCT_PER_CLICK = 60
const PCT_PER_CLICK_KEY = 'orca.tension.pctPerClick'

export function loadPctPerClick(): number {
  try {
    const v = Number(localStorage.getItem(PCT_PER_CLICK_KEY) ?? NaN)
    if (Number.isFinite(v) && v >= 1 && v <= 100) return v
  } catch {
    /* unreadable: the default */
  }
  return DEFAULT_PCT_PER_CLICK
}

export function savePctPerClick(v: number): void {
  try {
    localStorage.setItem(PCT_PER_CLICK_KEY, String(v))
  } catch {
    /* storage unavailable */
  }
}

// Clicks that bring a side from `pct` of the reference nearest to 100 %. A
// click is coarse (about 60 points), so a side in the yellow band usually gets
// none: one click would land it in the grey band above the reference.
export function clicksFor(pct: number, pctPerClick: number): number {
  return Math.max(0, Math.round((100 - pct) / Math.max(pctPerClick, 1)))
}

export const clicksText = (clicks: number) => (clicks === 0 ? 'leave · 1 click overshoots' : `${clicks} click${clicks === 1 ? '' : 's'}`)
export const STATUS_WORD: Record<Status, string> = {
  ok: 'ok',
  under: 'tension',
  low: 'loose',
  over: 'tighter',
  slack: 'slack',
  none: '',
}

export interface JointVerdict {
  status: Status
  pct: number | null
  slackDeg: number | null
  hint: string
}

export interface ProbeVerdict {
  joints: Record<string, { flex?: JointVerdict; extend?: JointVerdict; asymmetric: boolean }>
  summary: { status: Status; text: string } | null
  bands: typeof BANDS
}

// Breakaway and stroke are the same kind of reading (a current per side), so they share a key.
export const kindOf = (method: ProbeResult['method']) => (method === 'takeup' ? 'takeup' : 'breakaway')
export const key = (r: Pick<ProbeResult, 'joint' | 'sense' | 'method'>) => `${r.joint}/${r.sense}/${kindOf(r.method)}`

// One tendon side's breakaway over every pass of a run.
export interface BreakawayStat {
  n: number
  mean: number | null
  min: number | null
  max: number | null
  moveMean: number | null
  capped: number
  skipped: string | null
}

export function breakawayStats(results: ProbeResult[]): Map<string, BreakawayStat> {
  const out = new Map<string, BreakawayStat>()
  for (const r of results) {
    if (r.method === 'takeup') continue
    const k = key(r)
    const s = out.get(k) ?? { n: 0, mean: null, min: null, max: null, moveMean: null, capped: 0, skipped: null }
    if (r.skipped) {
      s.skipped = r.skipped
    } else if (r.breakaway_ma != null) {
      s.mean = ((s.mean ?? 0) * s.n + r.breakaway_ma) / (s.n + 1)
      s.min = s.min == null ? r.breakaway_ma : Math.min(s.min, r.breakaway_ma)
      s.max = s.max == null ? r.breakaway_ma : Math.max(s.max, r.breakaway_ma)
      if (r.move_ma != null) s.moveMean = s.moveMean == null ? r.move_ma : (s.moveMean * s.n + r.move_ma) / (s.n + 1)
      if (r.capped) s.capped += 1
      s.n += 1
    }
    out.set(k, s)
  }
  return out
}

// Latest result per tendon side and method, with breakaway averaged over the passes.
function index(results: ProbeResult[]): Map<string, ProbeResult> {
  const out = new Map<string, ProbeResult>()
  for (const r of results) out.set(key(r), r)
  for (const [k, s] of breakawayStats(results)) {
    const r = out.get(k)
    if (r && !s.skipped && s.n > 0) out.set(k, { ...r, skipped: null, breakaway_ma: s.mean, move_ma: s.moveMean })
  }
  return out
}

function slackOf(takeup: ProbeResult | undefined, breakaway: ProbeResult | undefined): number | null {
  if (!takeup || takeup.skipped || takeup.free_deg == null) return null
  if (takeup.stalled) return takeup.free_deg >= BANDS.slackDeg ? takeup.free_deg : 0
  // Ran to the cap: a free joint if it also breaks away easily, otherwise unknown.
  const ma = breakaway?.breakaway_ma
  return ma != null && ma < BANDS.freeMa ? 0 : null
}

// A reference only counts when it was made on the same motor family: Feetech
// currents run about twice Dynamixel's, so cross-family percentages mean nothing.
export function usableReference(
  probes: TensionProbes | null,
  method?: ProbeResult['method'] | null,
): { name: string | null; dataset: TensionProbeDataset | null; mismatch: string | null } {
  const name = probes?.reference ?? null
  const dataset = name ? (probes?.probes[name] ?? null) : null
  if (!dataset) return { name: null, dataset: null, mismatch: null }
  const hand = probes?.motor_type ?? null
  const ref = dataset.motor_type ?? null
  if (hand && ref && hand !== ref) {
    return { name, dataset: null, mismatch: `${name} was measured on ${ref} motors; this hand has ${hand}` }
  }
  // A stroke reads the current over a motion, a breakaway the current that starts one: not the same number.
  if (method && method !== 'takeup' && !dataset.methods.includes(method)) {
    return {
      name,
      dataset: null,
      mismatch: `${name} is a ${dataset.methods.filter((m) => m !== 'takeup').join('/')} run; a ${method} run can only be scored against a ${method} reference — run the check on the well-tensioned hand and keep it as the reference`,
    }
  }
  return { name, dataset, mismatch: null }
}

export function compareProbe(results: ProbeResult[], reference: TensionProbeDataset | null): ProbeVerdict {
  const got = index(results)
  const ref = reference ? index(reference.results) : null
  const joints: ProbeVerdict['joints'] = {}
  const counts: Record<Status, number> = { ok: 0, under: 0, low: 0, over: 0, slack: 0, none: 0 }
  for (const r of results) {
    const row = (joints[r.joint] ??= { asymmetric: false })
    if (row[r.sense]) continue
    const ba = got.get(`${r.joint}/${r.sense}/breakaway`)
    const tu = got.get(`${r.joint}/${r.sense}/takeup`)
    const slackDeg = slackOf(tu, ba)
    const mine = ba?.skipped ? null : (ba?.breakaway_ma ?? null)
    const theirs = ref?.get(`${r.joint}/${r.sense}/breakaway`)
    const refMa = theirs?.skipped ? null : (theirs?.breakaway_ma ?? null)
    const pct = mine != null && refMa ? (mine / refMa) * 100 : null
    let status: Status = 'none'
    let hint = 'not measured'
    if (slackDeg != null && slackDeg > 0) {
      status = 'slack'
      hint = `take-up stalled after ${slackDeg.toFixed(1)}° of motor travel: tendon slack on this side`
    } else if (pct != null) {
      status = pct < BANDS.low ? 'low' : pct < BANDS.under ? 'under' : pct > BANDS.over ? 'over' : 'ok'
      hint = `${mine} mA vs ${refMa} mA in the reference`
    } else if (mine != null) {
      hint = `breakaway ${mine} mA; no reference value for this joint`
    }
    const v: JointVerdict = { status, pct, slackDeg: slackDeg && slackDeg > 0 ? slackDeg : null, hint }
    row[r.sense] = v
    counts[status] += 1
  }
  for (const row of Object.values(joints)) {
    const f = got.get(`${findJoint(row, joints)}/flex/breakaway`)?.breakaway_ma
    const e = got.get(`${findJoint(row, joints)}/extend/breakaway`)?.breakaway_ma
    row.asymmetric = f != null && e != null && Math.abs(f - e) > BANDS.asymMa
  }
  const scored = counts.ok + counts.under + counts.over + counts.slack
  let summary: ProbeVerdict['summary'] = null
  if (scored > 0 && reference) {
    const status: Status = counts.slack ? 'slack' : counts.low ? 'low' : counts.under ? 'under' : counts.over ? 'over' : 'ok'
    const parts = [
      counts.ok && `${counts.ok} ok`,
      counts.under && `${counts.under} to tension`,
      counts.low && `${counts.low} loose`,
      counts.over && `${counts.over} tighter`,
      counts.slack && `${counts.slack} slack`,
    ].filter(Boolean)
    summary = { status, text: `${parts.join(', ')} of ${scored} tendon sides` }
  }
  return { joints, summary, bands: BANDS }
}

function findJoint(row: unknown, joints: ProbeVerdict['joints']): string {
  for (const [name, r] of Object.entries(joints)) if (r === row) return name
  return ''
}

export function useProbes(reload: unknown = null) {
  const [state, setState] = useState<TensionProbes | null>(null)
  const refresh = useCallback(() => void api.probes().then(setState).catch(failToBanner), [])
  useEffect(() => refresh(), [refresh, reload])
  return { state, refresh }
}

const when = (iso: string) => iso.slice(0, 16).replace('T', ' ')

// Settings control: which saved probe later probes are scored against.
export function ReferencePicker() {
  const { state, refresh } = useProbes()
  if (!state) return null
  const names = Object.keys(state.probes)
  const choose = (value: string) =>
    void api.probeReference(value || null).then(refresh).catch(failToBanner)
  const ref = state.reference ? state.probes[state.reference] : null
  return (
    <div className="flow-row">
      <label className="flow-field" title="Which saved probe every later probe's breakaway currents are scored against">
        <span>reference probe</span>
        <select value={state.reference ?? ''} onChange={(e) => choose(e.target.value)}>
          <option value="">none</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n} · {when(state.probes[n].recorded_at)}
              {state.probes[n].hand_key ? ` · ${state.probes[n].hand_key}` : ''}
              {state.probes[n].motor_type ? ` · ${state.probes[n].motor_type}` : ''}
            </option>
          ))}
        </select>
      </label>
      {ref && (
        <span className="flow-detail" title={ref.note ?? undefined}>
          {ref.joints.length} joints{ref.baseline ? ` · baseline ${ref.baseline}` : ''}
        </span>
      )}
      {usableReference(state).mismatch && (
        <span className="flow-info warn">{usableReference(state).mismatch} — not used for scoring</span>
      )}
      {names.length === 0 && <span className="flow-detail">no probe saved yet on this hand model</span>}
    </div>
  )
}

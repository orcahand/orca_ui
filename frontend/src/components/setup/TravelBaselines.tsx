// Named travel baselines (GT_01, ...): which one guided tensioning scores
// against, and the calibration snapshots that can become one. Every
// calibration leaves a snapshot; promoting names it for good.

import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { TravelBaselines as Baselines } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'
import { failToBanner } from './setupUtils'

const SHARED = '__shared__'

function when(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// GT_01, GT_02, ... after the highest GT_nn already there.
function nextName(names: string[]): string {
  const taken = names.map((n) => /^GT_(\d+)$/.exec(n)).filter(Boolean).map((m) => Number(m![1]))
  const next = taken.length ? Math.max(...taken) + 1 : 1
  return `GT_${String(next).padStart(2, '0')}`
}

export function useTravelBaselines() {
  const [state, setState] = useState<Baselines | null>(null)
  const refresh = useCallback(() => {
    api.baselines().then(setState).catch(failToBanner)
    api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
  }, [])
  const modelName = useAppStore((s) => s.handInfo?.model_name)
  // A finished calibration adds a snapshot: refetch when one ends.
  const finishedRun = useOperationStore((s) =>
    s.operation?.kind === 'calibrate' && s.operation.state === 'done' ? s.operation.run_id : null,
  )
  useEffect(() => refresh(), [refresh, modelName, finishedRun])
  return { state, refresh }
}

// The active-baseline picker (tension step settings).
export function BaselinePicker({ onChange }: { onChange?: () => void }) {
  const { state, refresh } = useTravelBaselines()
  if (!state) return null
  const names = Object.keys(state.baselines)
  const activate = (value: string) =>
    void api
      .baselineActivate(value === SHARED ? null : value)
      .then(() => {
        refresh()
        onChange?.()
      })
      .catch(failToBanner)
  const active = state.active ? state.baselines[state.active] : null
  return (
    <div className="flow-row">
      <label className="flow-field" title="Which motor-travel table every joint's spread is scored against">
        <span>baseline</span>
        <select value={state.active ?? SHARED} onChange={(e) => activate(e.target.value)}>
          <option value={SHARED}>shared v2.1 block</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n} · {state.baselines[n].source} · {when(state.baselines[n].recorded_at)}
            </option>
          ))}
        </select>
      </label>
      {active && (
        <span className="flow-detail" title={active.note ?? undefined}>
          {Object.keys(active.travel).length} joints
          {active.note ? ` · ${active.note}` : ''}
        </span>
      )}
      {names.length === 0 && (
        <span className="flow-detail">no baseline yet — calibrate, then promote the snapshot below</span>
      )}
    </div>
  )
}

// Snapshots of past calibrations with a promote control (calibrate step settings).
export function SnapshotPromoter({ limit = 4 }: { limit?: number }) {
  const { state, refresh } = useTravelBaselines()
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  if (!state) return null
  const snapshots = Object.entries(state.snapshots).slice(0, limit)
  const promotedFrom = new Map(
    Object.entries(state.baselines).flatMap(([n, b]) => (b.from_snapshot ? [[b.from_snapshot, n] as const] : [])),
  )
  const suggested = nextName(Object.keys(state.baselines))
  const promote = (snapshot: string) => {
    const target = name.trim() || suggested
    setBusy(snapshot)
    api
      .baselinePromote(snapshot, target, note.trim() || undefined)
      .then(() => {
        setName('')
        setNote('')
        refresh()
      })
      .catch(failToBanner)
      .finally(() => setBusy(null))
  }
  return (
    <div className="flow-baselines">
      <div className="flow-row">
        <span className="flow-detail">
          travel snapshots · active baseline: <b>{state.active ?? 'shared v2.1'}</b>
        </span>
      </div>
      {snapshots.length === 0 ? (
        <div className="flow-info">no calibration snapshot yet — every calibration run saves one here</div>
      ) : (
        <>
          <div className="flow-row">
            <label className="flow-field" title="Name for the baseline this snapshot becomes">
              <span>name</span>
              <input value={name} placeholder={suggested} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="flow-field" title="What was special about this hand state">
              <span>note</span>
              <input value={note} placeholder="e.g. clean hand after round 3" onChange={(e) => setNote(e.target.value)} />
            </label>
          </div>
          {snapshots.map(([id, snap]) => {
            const became = promotedFrom.get(id)
            return (
              <div key={id} className="flow-row flow-snapshot" title={id}>
                <span className={`setup-badge ${snap.source}`}>{snap.source}</span>
                <span className="flow-detail">
                  {when(snap.recorded_at)} · {snap.partial ? `${snap.joints?.length ?? '?'} of ` : ''}
                  {Object.keys(snap.travel).length} joints
                  {snap.note ? ` · ${snap.note}` : ''}
                </span>
                {snap.partial ? (
                  <span className="flow-detail" title="A subset or aborted run cannot become a baseline">
                    partial
                  </span>
                ) : became ? (
                  <span className="flow-detail">→ {became}</span>
                ) : (
                  <button
                    className="btn btn-secondary"
                    disabled={busy !== null}
                    title={`Promote this snapshot to ${name.trim() || suggested} and score tensioning against it`}
                    onClick={() => promote(id)}
                  >
                    {busy === id ? 'Promoting…' : `Promote to ${name.trim() || suggested}`}
                  </button>
                )}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}

// Per-joint travel check: active baseline vs the newest manual and automatic
// snapshots and the shared v2.1 block. Manual below automatic on the same hand
// means the motor wound slack before the joint moved.
export function TravelCheck() {
  const { state } = useTravelBaselines()
  const joints = useAppStore((s) => s.handInfo?.joints ?? [])
  if (!state) return null
  const ref = state.active ? state.baselines[state.active]?.travel : undefined
  const newest = (source: string) =>
    Object.entries(state.snapshots).find(([, snap]) => snap.source === source && !snap.partial)
  const manual = newest('manual')
  const auto = newest('auto')
  if (!ref && !manual && !auto) return null
  const pct = (value?: number, base?: number) =>
    value == null || !base ? '—' : `${Math.round((100 * value) / base)}%`
  const deg = (value?: number) => (value == null ? '—' : value.toFixed(1))
  const flag = (value?: number, base?: number) => {
    if (value == null || !base) return ''
    const ratio = value / base
    return ratio < 0.9 || ratio > 1.1 ? ' off' : ''
  }
  return (
    <div className="flow-baselines travel-check">
      <div className="flow-row">
        <span className="flow-detail">
          travel check · GT = <b>{state.active ?? 'none'}</b>
          {manual ? ` · manual ${when(manual[1].recorded_at)}` : ''}
          {auto ? ` · auto ${when(auto[1].recorded_at)}` : ''}
        </span>
      </div>
      <div className="travel-grid">
        <span className="travel-head">joint</span>
        <span className="travel-head">GT°</span>
        <span className="travel-head">manual</span>
        <span className="travel-head">auto</span>
        <span className="travel-head">auto/man</span>
        <span className="travel-head">v2.1</span>
        {joints
          .filter((j) => j.id !== 'wrist')
          .map((j) => {
            const g = ref?.[j.id]
            const m = manual?.[1].travel[j.id]
            const a = auto?.[1].travel[j.id]
            return (
              <Fragment key={j.id}>
                <span className="travel-joint">{j.id.replace('_', ' ')}</span>
                <span>{deg(g)}</span>
                <span className={flag(m, g)} title={deg(m)}>{pct(m, g)}</span>
                <span className={flag(a, g)} title={deg(a)}>{pct(a, g)}</span>
                <span className={flag(a, m)} title="automatic travel over manual travel">{pct(a, m)}</span>
                <span className={flag(state.shared[j.id], g)} title={deg(state.shared[j.id])}>
                  {pct(state.shared[j.id], g)}
                </span>
              </Fragment>
            )
          })}
      </div>
    </div>
  )
}

// This hand's last manual and last automatic calibration side by side, in
// motor degrees of travel, so both are known individually: the operator
// holds the stops by hand in one, the motors drive them in the other.
export function CalibrationRecords() {
  const { state } = useTravelBaselines()
  const joints = useAppStore((s) => s.handInfo?.joints ?? [])
  const handId = useAppStore((s) => s.handInfo?.hand_id ?? null)
  if (!state) return null
  const newest = (source: string) =>
    Object.entries(state.snapshots).find(
      ([, snap]) => snap.source === source && !snap.partial && (!handId || snap.hand_key === handId),
    )
  const manual = newest('manual')
  const auto = newest('auto')
  if (!manual && !auto) return null
  const deg = (value?: number) => (value == null ? '—' : value.toFixed(1))
  const diff = (a?: number, m?: number) =>
    a == null || m == null ? '—' : `${a - m >= 0 ? '+' : ''}${(a - m).toFixed(1)}`
  const flag = (a?: number, m?: number) => (a != null && m != null && Math.abs(a - m) > 5 ? ' off' : '')
  return (
    <div className="flow-baselines travel-check">
      <div className="flow-row">
        <span className="flow-detail">
          calibration records{handId ? ` · ${handId}` : ''}
          {manual ? ` · manual ${when(manual[1].recorded_at)}` : ' · no manual run yet'}
          {auto ? ` · automatic ${when(auto[1].recorded_at)}` : ' · no automatic run yet'}
        </span>
      </div>
      <div className="travel-grid four">
        <span className="travel-head">joint</span>
        <span className="travel-head">manual °</span>
        <span className="travel-head">auto °</span>
        <span className="travel-head">auto − manual</span>
        {joints.map((j) => {
          const m = manual?.[1].travel[j.id]
          const a = auto?.[1].travel[j.id]
          return (
            <Fragment key={j.id}>
              <span className="travel-joint">{j.id.replace('_', ' ')}</span>
              <span>{deg(m)}</span>
              <span>{deg(a)}</span>
              <span className={flag(a, m)} title="motor-driven travel minus hand-held travel">{diff(a, m)}</span>
            </Fragment>
          )
        })}
      </div>
      <p className="setup-copy dim">
        motor travel between the hard stops, from the newest complete run of each kind on this hand; both are also kept
        as calibration_manual.yaml and calibration_auto.yaml beside calibration.yaml
      </p>
    </div>
  )
}

// Slack per joint from the hand's own two sweeps: the final tensioning round's
// hand sweep (travel minus slack) against the calibration taken after it (travel
// plus slack). Needs no baseline from another hand.
export function SlackEstimate() {
  const estimate = useAppStore((s) => s.handInfo?.slack_estimate ?? null)
  const joints = useAppStore((s) => s.handInfo?.joints ?? [])
  if (!estimate) return null
  const rows = joints.filter((j) => estimate.joints[j.id])
  if (rows.length === 0) return null
  const flag = (slack: number) => (slack > 3 ? ' off' : '')
  return (
    <div className="flow-baselines travel-check">
      <div className="flow-row">
        <span className="flow-detail">
          slack from this hand's own sweeps · tensioned {when(estimate.tensioned_at)} · calibrated{' '}
          {when(estimate.calibrated_at)}
        </span>
      </div>
      <div className="travel-grid slack-grid">
        <span className="travel-head">joint</span>
        <span className="travel-head" title="hand sweep, final tensioning round (motor degrees)">sweep°</span>
        <span className="travel-head" title="motor-driven calibration (motor degrees)">motor°</span>
        <span className="travel-head" title="(motor − sweep) / 2">slack°</span>
        <span className="travel-head" title="(motor + sweep) / 2: this hand's travel without slack">travel°</span>
        {rows.map((j) => {
          const e = estimate.joints[j.id]
          return (
            <Fragment key={j.id}>
              <span className="travel-joint">{j.id.replace('_', ' ')}</span>
              <span>{e.sweep_deg.toFixed(1)}</span>
              <span>{e.motor_deg.toFixed(1)}</span>
              <span className={flag(e.slack_deg)}>{e.slack_deg.toFixed(1)}</span>
              <span>{e.travel_deg.toFixed(1)}</span>
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}

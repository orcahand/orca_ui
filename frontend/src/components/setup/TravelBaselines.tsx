// The calibration snapshots kept in the travel_baselines section: every
// calibration leaves one, and the Calibrate step shows the newest of each kind.

import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { TravelBaselines as Baselines } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'
import { failToBanner } from './setupUtils'

function when(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
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

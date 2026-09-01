// Poses tab: preset pose grid, movement scripts (demos), the trajectory
// library with record/replay, and the cable-integrity stress test. Everything
// that moves the hand needs torque, which is never auto-enabled — the tab
// toolbar hosts a torque toggle for convenience.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { DemoEntry, PoseEntry, TrajectoryEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useControlGate, useOperationStore } from '../../state/operationStore'
import { DemoList } from '../poses/DemoList'
import { PoseGrid } from '../poses/PoseGrid'
import { StressTestPanel } from '../poses/StressTestPanel'
import { TrajectoryPanel } from '../poses/TrajectoryPanel'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function PosesView() {
  const [poses, setPoses] = useState<PoseEntry[]>([])
  const [demos, setDemos] = useState<DemoEntry[]>([])
  const [trajectories, setTrajectories] = useState<TrajectoryEntry[]>([])

  const refreshPoses = useCallback(() => {
    api
      .poses()
      .then((r) => setPoses(r.poses))
      .catch(fail)
  }, [])
  const refreshTrajectories = useCallback(() => {
    api
      .trajectories()
      .then((r) => setTrajectories(r.trajectories))
      .catch(fail)
  }, [])

  useEffect(() => {
    refreshPoses()
    refreshTrajectories()
    api
      .demos()
      .then((r) => setDemos(r.demos))
      .catch(fail)
  }, [refreshPoses, refreshTrajectories])

  // A finished record adds a trajectory: refresh the list once per run when
  // its terminal snapshot arrives.
  const operation = useOperationStore((s) => s.operation)
  const handledRun = useRef<string | null>(null)
  useEffect(() => {
    if (
      operation?.kind === 'record' &&
      operation.state === 'done' &&
      handledRun.current !== operation.run_id
    ) {
      handledRun.current = operation.run_id
      refreshTrajectories()
    }
  }, [operation, refreshTrajectories])

  return (
    <>
      <TorqueToolbar />
      <PoseGrid poses={poses} onChanged={refreshPoses} />
      <DemoList demos={demos} />
      <TrajectoryPanel
        trajectories={trajectories}
        onChanged={refreshTrajectories}
      />
      <StressTestPanel />
    </>
  )
}

// Torque toggle for the whole tab — pose apply and replay need torque
// already on (mirrors MotorPanel's enable/disable pair). Movement scripts
// are the exception: they enable torque themselves and restore it after.
function TorqueToolbar() {
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const gate = useControlGate()
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState(false)

  const locked = !gate.manualAllowed
  const hint = locked
    ? (gate.reason ?? undefined)
    : !motors
      ? 'motor bus unavailable'
      : undefined

  const toggle = async () => {
    setBusy(true)
    try {
      if (torqueOn) await api.torqueDisable()
      else await api.torqueEnable()
      setError(null)
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="poses-toolbar">
      <span className="poses-toolbar-label">torque</span>
      <span className={`torque-state${torqueOn ? ' on' : ''}`}>
        {torqueOn ? 'ON' : 'OFF'}
      </span>
      <button
        className={`btn ${torqueOn ? 'btn-danger' : 'btn-primary'}`}
        disabled={busy || locked || !motors}
        title={hint}
        onClick={() => void toggle()}
      >
        {torqueOn ? 'Disable Torque' : 'Enable Torque'}
      </button>
      <span className="poses-toolbar-hint">
        pose apply and replay need torque on — never enabled automatically;
        movement scripts enable it for the run and put it back
      </span>
    </div>
  )
}

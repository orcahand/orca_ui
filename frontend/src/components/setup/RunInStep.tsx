// Step 3: loop the collision-free full-range sequence for a few minutes so the
// freshly tensioned tendons settle. Needs a calibrated hand.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { FlowProgress, FlowRunning, FlowStep, type StepState } from './FlowStep'
import { failToBanner, readRunInDone, runInCompleted, shortDate, writeRunInDone } from './setupUtils'

const MINUTES = [1, 2, 5, 10, 15]
// Mirrors RUN_IN_SPEEDS in orca_ui/hand/operations/player.py.
const SPEEDS = [1, 2, 3, 4]
export function RunInStep({
  state,
  calibrated,
}: {
  state: StepState
  calibrated: boolean
}) {
  const gate = useStartGate('motors')
  const model = useAppStore((s) => s.handInfo?.model_name)
  const torque = useAppStore((s) => s.status?.torque_enabled ?? false)
  const operation = useOperationStore((s) => s.operation)
  const active =
    operation?.kind === 'run_in' && isOperationActive(operation) ? operation : null
  const [minutes, setMinutes] = useState(5)
  const [speed, setSpeed] = useState(3)
  const [doneAt, setDoneAt] = useState<string | null>(null)
  useEffect(() => setDoneAt(readRunInDone(model)), [model])

  const finishedId = runInCompleted(operation) ? operation!.run_id : null
  useEffect(() => {
    if (!finishedId || !model) return
    const now = new Date().toISOString()
    writeRunInDone(model, now)
    setDoneAt(now)
  }, [finishedId, model])

  const start = async () => {
    try {
      if (!torque) await api.torqueEnable()
      await api.operationStart('run_in', { duration_s: minutes * 60, speed })
    } catch (error) {
      failToBanner(error)
    }
  }

  const duration = Number(active?.params.duration_s ?? minutes * 60)
  const left = active?.progress != null ? Math.ceil((1 - active.progress) * duration) : null
  const blocked = gate.blocked || !calibrated

  return (
    <FlowStep
      n={3}
      title="Run-in"
      state={active ? 'running' : state}
      chip={doneAt ? shortDate(doneAt) : `${minutes} min · ×${speed}`}
      info="Moves every joint through its full range in a collision-free loop. Keep the hand free."
      settings={
        <>
          <div className="flow-row">
            {MINUTES.map((m) => (
              <button
                key={m}
                className={`finger-chip${m === minutes ? ' has-selection' : ''}`}
                onClick={() => setMinutes(m)}
              >
                {m} min
              </button>
            ))}
          </div>
          <div className="flow-row" title="Speed of the motion; one pass takes about 15 s at ×1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                className={`finger-chip${s === speed ? ' has-selection' : ''}`}
                onClick={() => setSpeed(s)}
              >
                ×{s}
              </button>
            ))}
          </div>
        </>
      }
    >
      {active ? (
        <>
          <FlowRunning
            phase={active.phase}
            detail={left !== null ? `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : null}
          />
          <FlowProgress value={active.progress} />
        </>
      ) : (
        <button
          className="btn btn-primary"
          disabled={blocked}
          title={gate.reason ?? (!calibrated ? 'calibrate first' : undefined)}
          onClick={() => void start()}
        >
          ▶ {minutes} min
        </button>
      )}
    </FlowStep>
  )
}

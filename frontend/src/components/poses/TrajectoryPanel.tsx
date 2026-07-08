// Trajectory library: recorded trajectories with replay (speed ×0.5/×1/×2 +
// loop) and delete, plus the record controls (continuous/waypoints).
// Recording needs joint encoders and disables torque for its duration
// (posing the hand by hand); ending it goes through operation input — the
// transport bar owns capture / stop & save once recording runs.

import { useState } from 'react'
import { api } from '../../api/rest'
import { LIBRARY_NAME_RE, type TrajectoryEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useStartGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'

const SPEEDS = [0.5, 1, 2]

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const clampFrequency = (value: number) =>
  Math.min(60, Math.max(1, Math.round(value)))

export function TrajectoryPanel({
  trajectories,
  onChanged,
}: {
  trajectories: TrajectoryEntry[]
  onChanged(): void
}) {
  const replayGate = useStartGate('motors')
  const recordGate = useStartGate('encoders')
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)

  const [speeds, setSpeeds] = useState<Record<string, number>>({})
  const [loops, setLoops] = useState<Record<string, boolean>>({})
  const [mode, setMode] = useState<'continuous' | 'waypoints'>('continuous')
  const [frequency, setFrequency] = useState(50)
  const [recordName, setRecordName] = useState('')

  const replayBlocked = replayGate.blocked || !torqueOn
  const replayReason =
    replayGate.reason ?? (!torqueOn ? 'enable torque to replay' : null)

  const replay = (name: string) =>
    void api
      .operationStart('replay', {
        name,
        speed: speeds[name] ?? 1,
        loop: loops[name] ?? false,
      })
      .catch(fail)

  const remove = (name: string) => {
    if (!window.confirm(`Delete trajectory "${name}"?`)) return
    void api.trajectoryDelete(name).then(onChanged).catch(fail)
  }

  const nameValid = LIBRARY_NAME_RE.test(recordName)
  const recordBlocked = recordGate.blocked || !nameValid
  const recordHint = recordGate.blocked
    ? recordGate.reason
    : recordName.length === 0
      ? 'name the recording first'
      : !nameValid
        ? 'letters, digits, _ and - only (max 64)'
        : null

  const startRecord = () => {
    if (recordBlocked) return
    void api
      .operationStart('record', {
        mode,
        name: recordName,
        ...(mode === 'continuous' ? { frequency } : {}),
      })
      .then(() => setRecordName(''))
      .catch(fail)
  }

  return (
    <Panel title="Trajectories">
      {trajectories.length === 0 ? (
        <div className="panel-empty">
          no recordings yet — record one below
        </div>
      ) : (
        <>
          {replayBlocked && <div className="panel-hint">{replayReason}</div>}
          <table className="traj-table">
            <thead>
              <tr>
                <th>name</th>
                <th>type</th>
                <th>frames</th>
                <th>duration</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {trajectories.map((traj) => (
                <tr key={traj.name}>
                  <td className="traj-name">{traj.name}</td>
                  <td>
                    <span className="type-badge">
                      {traj.type === 'continuous' ? 'continuous' : 'waypoints'}
                    </span>
                  </td>
                  <td>{traj.frames}</td>
                  <td>
                    {traj.duration_s != null
                      ? `${traj.duration_s.toFixed(1)}s`
                      : '—'}
                  </td>
                  <td>
                    <span className="traj-actions">
                      <select
                        value={speeds[traj.name] ?? 1}
                        title="playback speed"
                        onChange={(e) =>
                          setSpeeds((prev) => ({
                            ...prev,
                            [traj.name]: Number(e.target.value),
                          }))
                        }
                      >
                        {SPEEDS.map((speed) => (
                          <option key={speed} value={speed}>
                            ×{speed}
                          </option>
                        ))}
                      </select>
                      <label className="traj-loop">
                        <input
                          type="checkbox"
                          checked={loops[traj.name] ?? false}
                          onChange={(e) =>
                            setLoops((prev) => ({
                              ...prev,
                              [traj.name]: e.target.checked,
                            }))
                          }
                        />
                        loop
                      </label>
                      <button
                        className="btn btn-primary"
                        disabled={replayBlocked}
                        title={replayReason ?? `replay ${traj.name}`}
                        onClick={() => replay(traj.name)}
                      >
                        ▶
                      </button>
                      <button
                        className="btn btn-danger"
                        title={`delete ${traj.name}`}
                        onClick={() => remove(traj.name)}
                      >
                        🗑
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="record-form">
        <span className="record-form-label">record</span>
        <div className="toolbar">
          <label className="toggle-label">
            <input
              type="radio"
              name="record-mode"
              checked={mode === 'continuous'}
              onChange={() => setMode('continuous')}
            />
            continuous
          </label>
          <label className="toggle-label">
            <input
              type="radio"
              name="record-mode"
              checked={mode === 'waypoints'}
              onChange={() => setMode('waypoints')}
            />
            waypoints
          </label>
        </div>
        {mode === 'continuous' && (
          <label className="record-freq">
            freq
            <input
              type="number"
              min={1}
              max={60}
              value={frequency}
              onChange={(e) =>
                setFrequency(clampFrequency(Number(e.target.value) || 1))
              }
            />
            Hz
          </label>
        )}
        <input
          className="record-name"
          type="text"
          placeholder="recording_name"
          value={recordName}
          onChange={(e) => setRecordName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') startRecord()
          }}
        />
        <button
          className="btn btn-danger"
          disabled={recordBlocked}
          title={recordHint ?? 'start recording'}
          onClick={startRecord}
        >
          ● start recording
        </button>
        <span className={`record-note${recordHint ? ' warn' : ''}`}>
          {recordHint ?? 'recording disables torque — pose the hand by hand'}
        </span>
      </div>
    </Panel>
  )
}

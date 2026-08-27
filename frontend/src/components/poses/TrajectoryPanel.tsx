// Trajectory library: recorded trajectories with replay (speed ×0.5–×8 +
// loop + optional interpolation steps) and delete, plus the record controls
// (continuous / waypoints / motor waypoints — the last captures RAW motor
// positions and replays as direct motor stepping, calibration required).
// Joint recording needs a joint-angle source (encoders, or a calibrated
// hand's motor-derived estimate) and disables torque for its duration
// (posing the hand by hand); ending it goes through operation input — the
// transport bar owns capture / stop & save once recording runs.

import { lazy, Suspense, useState } from 'react'
import { api } from '../../api/rest'
import { LIBRARY_NAME_RE, type TrajectoryEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useStartGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'

// The 3D waypoint editor pulls in three.js — load it only when opened.
const WaypointEditor = lazy(() =>
  import('./WaypointEditor').then((m) => ({ default: m.WaypointEditor })),
)

const SPEEDS = [0.5, 1, 2, 4, 8]

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
  const recordGate = useStartGate('joints')
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)

  const motorsCalibrated =
    useAppStore((s) => s.handInfo?.calibration.motors) === true

  const [speeds, setSpeeds] = useState<Record<string, number>>({})
  const [loops, setLoops] = useState<Record<string, boolean>>({})
  // Interpolation steps per segment, as typed. '' = default behavior
  // (cruise-speed glide for joint waypoints, 0 = direct for motor ones).
  const [steps, setSteps] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<string | null>(null)
  const [mode, setMode] = useState<
    'continuous' | 'waypoints' | 'motor_waypoints'
  >('continuous')
  const [frequency, setFrequency] = useState(50)
  const [recordName, setRecordName] = useState('')

  const replayBlocked = replayGate.blocked || !torqueOn
  const replayReason =
    replayGate.reason ?? (!torqueOn ? 'enable torque to replay' : null)

  const replay = (traj: TrajectoryEntry) => {
    const raw = steps[traj.name] ?? ''
    const parsed = parseInt(raw, 10)
    const interp =
      raw !== '' && Number.isFinite(parsed)
        ? Math.min(200, Math.max(0, parsed))
        : traj.type === 'motor_waypoints'
          ? 0
          : null
    void api
      .operationStart('replay', {
        name: traj.name,
        speed: speeds[traj.name] ?? 1,
        loop: loops[traj.name] ?? false,
        ...(interp !== null ? { interp_steps: interp } : {}),
      })
      .catch(fail)
  }

  const toMotor = (name: string) => {
    void api
      .trajectoryToMotor(name)
      .then((r) => {
        onChanged()
        useAppStore.getState().setError(null)
        return r
      })
      .catch(fail)
  }

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
                    <span
                      className="type-badge"
                      title={
                        traj.type === 'motor_waypoints'
                          ? 'raw motor positions — replayed as direct motor stepping (needs a calibrated hand)'
                          : undefined
                      }
                    >
                      {traj.type === 'continuous'
                        ? 'continuous'
                        : traj.type === 'motor_waypoints'
                          ? 'motor'
                          : 'waypoints'}
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
                      {traj.type !== 'continuous' && (
                        <input
                          type="number"
                          min={0}
                          max={200}
                          placeholder={
                            traj.type === 'motor_waypoints' ? '0' : 'glide'
                          }
                          title={
                            'interpolation steps per segment — 0 jumps ' +
                            'straight to each point; empty keeps the ' +
                            (traj.type === 'motor_waypoints'
                              ? 'direct stepping default (0)'
                              : 'smooth cruise-speed glide with waypoint holds')
                          }
                          value={steps[traj.name] ?? ''}
                          onChange={(e) =>
                            setSteps((prev) => ({
                              ...prev,
                              [traj.name]: e.target.value,
                            }))
                          }
                          style={{ width: 48 }}
                        />
                      )}
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
                        disabled={
                          replayBlocked ||
                          (traj.type === 'motor_waypoints' && !motorsCalibrated)
                        }
                        title={
                          traj.type === 'motor_waypoints' && !motorsCalibrated
                            ? 'motor recordings replay raw motor positions — calibrate the hand first'
                            : (replayReason ?? `replay ${traj.name}`)
                        }
                        onClick={() => replay(traj)}
                      >
                        ▶
                      </button>
                      {traj.type === 'discrete_waypoints' && (
                        <button
                          className="btn btn-secondary"
                          disabled={!motorsCalibrated}
                          title={
                            motorsCalibrated
                              ? `translate ${traj.name} to raw motor positions (saved as ${traj.name}_motor)`
                              : 'joint→motor translation needs a calibrated hand'
                          }
                          onClick={() => toMotor(traj.name)}
                        >
                          →M
                        </button>
                      )}
                      <button
                        className="btn btn-secondary"
                        disabled={traj.type !== 'discrete_waypoints'}
                        title={
                          traj.type === 'continuous'
                            ? 'continuous recordings are sampled motion — only joint waypoint sequences are editable'
                            : traj.type === 'motor_waypoints'
                              ? 'motor-space recordings have no joint pose to edit in 3D'
                              : `edit ${traj.name}'s steps in 3D`
                        }
                        onClick={() => setEditing(traj.name)}
                      >
                        ✎
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
          <label
            className="toggle-label"
            title="capture RAW motor positions per waypoint — replays as direct motor stepping (needs a calibrated hand to replay)"
          >
            <input
              type="radio"
              name="record-mode"
              checked={mode === 'motor_waypoints'}
              onChange={() => setMode('motor_waypoints')}
            />
            motor waypoints
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
      {editing && (
        <Suspense fallback={null}>
          <WaypointEditor
            name={editing}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null)
              onChanged()
            }}
          />
        </Suspense>
      )}
    </Panel>
  )
}

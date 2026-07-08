// Preset pose grid: built-ins (dashed "placeholder" styling until tuned on
// the real hand) + user poses with delete, plus the capture-current-pose
// tile. Apply is a one-shot endpoint — it never spawns the transport bar.

import { useState } from 'react'
import { api } from '../../api/rest'
import { LIBRARY_NAME_RE, type PoseEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useControlGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function PoseGrid({
  poses,
  onChanged,
}: {
  poses: PoseEntry[]
  onChanged(): void
}) {
  const gate = useControlGate()
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const encoders = useAppStore(
    (s) => s.status?.capabilities?.encoders ?? false,
  )
  const setError = useAppStore((s) => s.setError)
  const [capturing, setCapturing] = useState(false)
  const [captureName, setCaptureName] = useState('')

  const applyBlocked = !gate.manualAllowed || !torqueOn
  const applyHint = !gate.manualAllowed
    ? (gate.reason ?? undefined)
    : !torqueOn
      ? 'enable torque to apply poses'
      : undefined

  const apply = (name: string) =>
    void api
      .poseApply(name)
      .then(() => setError(null))
      .catch(fail)

  const remove = (name: string) => {
    if (!window.confirm(`Delete pose "${name}"?`)) return
    void api.poseDelete(name).then(onChanged).catch(fail)
  }

  const nameValid = LIBRARY_NAME_RE.test(captureName)
  const capture = () => {
    if (!nameValid) return
    void api
      .poseCapture(captureName)
      .then(() => {
        setCaptureName('')
        setCapturing(false)
        onChanged()
      })
      .catch(fail)
  }

  return (
    <Panel title="Preset Poses">
      {applyBlocked && <div className="panel-hint">{applyHint}</div>}
      <div className="pose-grid">
        {poses.map((pose) => (
          <div key={pose.name} className="pose-cell">
            <button
              className={`pose-tile${pose.placeholder ? ' placeholder' : ''}`}
              disabled={applyBlocked}
              title={applyHint ?? `apply ${pose.name}`}
              onClick={() => apply(pose.name)}
            >
              <span className="pose-tile-name">{pose.name}</span>
              <span className="pose-tile-hint">
                {pose.placeholder ? 'placeholder' : (pose.saved_at ?? 'saved')}
              </span>
            </button>
            {!pose.builtin && (
              <button
                className="pose-tile-delete"
                title={`delete ${pose.name}`}
                onClick={() => remove(pose.name)}
              >
                ✕
              </button>
            )}
          </div>
        ))}
        <div className="pose-cell">
          {capturing ? (
            <div className="pose-tile capture-form">
              <input
                type="text"
                autoFocus
                placeholder="pose_name"
                value={captureName}
                onChange={(e) => setCaptureName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') capture()
                  if (e.key === 'Escape') setCapturing(false)
                }}
              />
              <div className="capture-form-actions">
                <button
                  className="btn btn-primary"
                  disabled={!nameValid || !encoders}
                  title={
                    !encoders
                      ? 'capture needs joint encoders (measured pose)'
                      : !nameValid
                        ? 'letters, digits, _ and - only (max 64)'
                        : undefined
                  }
                  onClick={capture}
                >
                  save
                </button>
                <button
                  className="btn btn-secondary"
                  onClick={() => setCapturing(false)}
                >
                  cancel
                </button>
              </div>
              {captureName.length > 0 && !nameValid && (
                <span className="pose-tile-hint">
                  letters, digits, _ and - only
                </span>
              )}
            </div>
          ) : (
            <button
              className="pose-tile capture"
              title="save the current measured pose"
              onClick={() => setCapturing(true)}
            >
              <span className="pose-tile-name">+ capture</span>
              <span className="pose-tile-hint">current pose</span>
            </button>
          )}
        </div>
      </div>
    </Panel>
  )
}

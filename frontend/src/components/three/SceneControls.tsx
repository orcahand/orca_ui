// Layer toggles for the 3D view + the mock-only joint-sweep dev panel used
// to verify per-joint sign/offset calibration.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function SceneControls({
  onReloadCalibration,
}: {
  onReloadCalibration: () => void
}) {
  const scene = useAppStore((s) => s.scene)
  const setScene = useAppStore((s) => s.setScene)
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const setError = useAppStore((s) => s.setError)
  const [sweeping, setSweeping] = useState<string | null>(null)
  const [sweepJoint, setSweepJoint] = useState('index_mcp')

  const caps = status?.capabilities

  const toggleSweep = async () => {
    try {
      if (sweeping) {
        const result = await api.mockJointSweep(null)
        setSweeping(result.sweeping)
      } else {
        const result = await api.mockJointSweep(sweepJoint)
        setSweeping(result.sweeping)
      }
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <div className="toolbar">
        <label className="toggle-label" title="translucent hand posed from the naive motor estimate">
          <input
            type="checkbox"
            checked={scene.ghost}
            onChange={(e) => setScene({ ghost: e.target.checked })}
            disabled={!caps?.motors}
          />
          ghost (motor estimate)
        </label>
        <label className="toggle-label" title="one resultant-force arrow per finger, at the sensor">
          <input
            type="checkbox"
            checked={scene.forceResultant}
            onChange={(e) => setScene({ forceResultant: e.target.checked })}
            disabled={!caps?.tactile}
          />
          resultant force
        </label>
        <label className="toggle-label" title="one arrow per taxel (needs the taxel or combined stream mode)">
          <input
            type="checkbox"
            checked={scene.forceTaxels}
            onChange={(e) => setScene({ forceTaxels: e.target.checked })}
            disabled={!caps?.tactile}
          />
          taxel forces
        </label>
        <label className="toggle-label" title="joint rings colored by tracking error">
          <input
            type="checkbox"
            checked={scene.jointGlow}
            onChange={(e) => setScene({ jointGlow: e.target.checked })}
            disabled={!caps?.encoders}
          />
          joint glow
        </label>
      </div>

      {handInfo?.mock && (
        <div className="toolbar" title="drive one joint through its ROM to verify the 3D sign/offset calibration">
          <label className="toggle-label" style={{ gap: 6 }}>
            sweep
            <select
              value={sweepJoint}
              onChange={(e) => setSweepJoint(e.target.value)}
              disabled={sweeping !== null}
            >
              {handInfo.joints.map((joint) => (
                <option key={joint.id} value={joint.id}>
                  {joint.id}
                </option>
              ))}
            </select>
          </label>
          <button
            className={`btn ${sweeping ? 'btn-danger' : 'btn-scan'}`}
            style={{ margin: 2 }}
            onClick={() => void toggleSweep()}
          >
            {sweeping ? `stop ${sweeping}` : 'sweep'}
          </button>
        </div>
      )}

      <button
        className="btn btn-secondary"
        title="re-read models/hand_v2/joint_calibration.yaml"
        onClick={onReloadCalibration}
      >
        Reload cal
      </button>
    </div>
  )
}

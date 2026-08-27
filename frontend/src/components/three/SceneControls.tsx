// Layer toggles for the 3D view + the mock-only joint-sweep dev panel used
// to verify each joint's motion direction against the URDF.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'

export function SceneControls() {
  const scene = useAppStore((s) => s.scene)
  const setScene = useAppStore((s) => s.setScene)
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const setError = useAppStore((s) => s.setError)
  const [sweeping, setSweeping] = useState<string | null>(null)
  const [sweepJoint, setSweepJoint] = useState('index_mcp')
  const teleopActive = useTeleopStore((s) => isTeleopActive(s.session))

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

  // Toggles for layers the connected hand can't produce are hidden outright
  // (not disabled) — a greyed-out "taxel forces" only confuses the owner of a
  // sensorless hand. The ghost compares the motor estimate against the
  // measured pose, so it needs both motors and encoders to mean anything.
  const showGhost = Boolean(caps?.motors && caps?.encoders)
  const showForces = Boolean(caps?.tactile)
  const showGlow = Boolean(caps?.encoders)
  const anyToggle = showGhost || showForces || showGlow || teleopActive

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <div className="toolbar">
        <label className="toggle-label" title="freeze the camera: orbit, pan and zoom are ignored until unlocked">
          <input
            type="checkbox"
            checked={scene.lockView}
            onChange={(e) => setScene({ lockView: e.target.checked })}
          />
          lock view
        </label>
      </div>
      {anyToggle && (
        <div className="toolbar">
          {showGhost && (
            <label className="toggle-label" title="translucent hand posed from the naive motor estimate">
              <input
                type="checkbox"
                checked={scene.ghost}
                onChange={(e) => setScene({ ghost: e.target.checked })}
              />
              ghost (motor estimate)
            </label>
          )}
          {showForces && (
            <label className="toggle-label" title="one resultant-force arrow per finger, at the sensor">
              <input
                type="checkbox"
                checked={scene.forceResultant}
                onChange={(e) => setScene({ forceResultant: e.target.checked })}
              />
              resultant force
            </label>
          )}
          {showForces && (
            <label className="toggle-label" title="one arrow per taxel (needs the taxel or combined stream mode)">
              <input
                type="checkbox"
                checked={scene.forceTaxels}
                onChange={(e) => setScene({ forceTaxels: e.target.checked })}
              />
              taxel forces
            </label>
          )}
          {showGlow && (
            <label className="toggle-label" title="joint rings colored by tracking error">
              <input
                type="checkbox"
                checked={scene.jointGlow}
                onChange={(e) => setScene({ jointGlow: e.target.checked })}
              />
              joint glow
            </label>
          )}
          {teleopActive && (
            <label
              className="toggle-label"
              title="cyan ghost posed from the live teleop retargeter output"
            >
              <input
                type="checkbox"
                checked={scene.teleopGhost}
                onChange={(e) => setScene({ teleopGhost: e.target.checked })}
              />
              teleop ghost
            </label>
          )}
        </div>
      )}

      {handInfo?.mock && (
        <div className="toolbar" title="drive one joint through its ROM to verify its 3D motion direction">
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
    </div>
  )
}

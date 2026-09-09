// Layer toggles for the 3D view + the mock-only joint-sweep dev panel used
// to verify each joint's motion direction against the URDF.

import { useState } from 'react'
import { api } from '../../api/rest'
import type { PoseSource } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'

// Which stream poses the model. "auto" is what you want almost always: the
// motors are polled while limp and left alone once torque is on, so reads stop
// competing with commands for a half-duplex bus. The pins exist for the two
// cases auto cannot serve -- watching real motion during a commanded move, and
// checking the commanded pose on a hand that cannot be read.
function PoseSourceControl() {
  const control = useAppStore((s) => s.control)
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const encoders = useAppStore((s) => s.status?.capabilities?.encoders ?? false)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState(false)

  // Encoder hands pose from measured angles; there is no choice to make.
  if (!motors || encoders || !control) return null

  const mode = control.pose_source
  const set = (next: PoseSource) => {
    setBusy(true)
    api
      .setPoseSource(next)
      .then(() => setError(null))
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false))
  }
  const pin = (target: PoseSource, label: string, title: string) => (
    <label className="toggle-label" title={title}>
      <input
        type="checkbox"
        checked={mode === target}
        disabled={busy}
        onChange={(e) => set(e.target.checked ? target : 'auto')}
      />
      {label}
    </label>
  )

  return (
    <div className="toolbar">
      <span style={{ fontSize: 10, color: 'var(--dim)' }}>
        pose: {mode === 'auto' ? `auto (${control.effective_pose_source})` : mode}
      </span>
      {pin('estimate', 'always motor estimate',
           'Keep reading the motors even while torqued. Shows real motion ' +
           'rather than the command, at the cost of bus reads competing with ' +
           'the commands being streamed.')}
      {pin('target', 'always commanded',
           'Never read the motors. Shows what was commanded, which cannot ' +
           'reveal tracking error — but costs no bus traffic.')}
    </div>
  )
}

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
      <PoseSourceControl />
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

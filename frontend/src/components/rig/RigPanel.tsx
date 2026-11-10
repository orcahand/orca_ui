// The calibration rig's controls on the dashboard (docs/rig-dashboard.md). The server keeps
// the safety rules: the configured slow speed, torque off whenever the plate stops, E-STOP
// drops the plate too, and the plate never turns while the hand moves (and the reverse).

import { useState } from 'react'
import { Panel } from '../common/Panel'
import { refreshRig, rigConnected, useRig } from '../../state/rigStore'
import { visualApi } from '../visual/api'

export function RigPanel() {
  const presence = useRig((s) => s.presence)
  const info = useRig((s) => s.info)
  const twinState = useRig((s) => s.twinState)
  const showTower = useRig((s) => s.showTower)
  const camera = useRig((s) => s.camera)
  const overlay = useRig((s) => s.overlay)
  const toggle = useRig((s) => s.toggle)
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  if (!presence) return null
  const t = presence.turntable
  const connected = rigConnected(presence)
  const angle = twinState?.angle ?? t.angle
  const travel = twinState?.travel ?? info?.travel ?? 320
  const swap = twinState?.swap_angle ?? info?.swap_angle ?? 180
  const blocked = presence.hand_blocker
  const run = async (what: string, fn: () => Promise<unknown>) => {
    setBusy(true)
    setNote(`${what}…`)
    try {
      await fn()
      setNote(null)
    } catch (e) {
      setNote(`${what}: ${(e as Error).message}`)
    } finally {
      setBusy(false)
      void refreshRig()
    }
  }
  const go = () => {
    const a = Number(target)
    if (!Number.isFinite(a) || a < 0 || a > travel) return setNote(`angle 0…${travel}°`)
    void run(`to ${a}°`, () => visualApi.move(a))
  }
  const disabled = busy || t.busy || !connected

  if (!connected) {
    return (
      <Panel title="Calibration rig">
        <div className="rig-panel">
          <span className="dim">{presence.present ? 'rig board found, not connected' : 'no rig board'}</span>
          {presence.warnings.map((w) => <div key={w} className="rig-warning">{w}</div>)}
          <button className="btn btn-secondary" disabled={busy} onClick={() => run('looking for the rig', visualApi.rigScan)}>
            Look for the rig
          </button>
          {note && <div className="rig-note">{note}</div>}
        </div>
      </Panel>
    )
  }

  return (
    <Panel title="Calibration rig">
      <div className="rig-panel">
        <div className="rig-angle">
          <span className="rig-angle-value">{angle === null || angle === undefined ? '—' : `${angle.toFixed(1)}°`}</span>
          <span className="dim">
            plate · {t.homed ? (t.zero_from === 'calibration' ? 'zero from calibration' : 'homed') : 'not homed'}
            {t.torque ? ' · torque on' : ' · torque off'}
            {t.busy ? ' · turning' : ''}
          </span>
        </div>
        <div className="dim rig-board">
          {presence.model ?? 'motor ?'} · {presence.port ?? '?'} · {presence.reason}
          {presence.identity_claim ? ` · ID claims ${presence.identity_claim}` : ''}
        </div>
        {presence.warnings.map((w) => <div key={w} className="rig-warning">{w}</div>)}
        {blocked && <div className="rig-warning">{blocked}</div>}
        <div className="rig-row">
          <input
            className="rig-input"
            type="number"
            min={0}
            max={travel}
            step={5}
            placeholder={`0…${travel}°`}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && go()}
            disabled={disabled || !t.homed}
            style={{ width: 90 }}
          />
          <button className="btn btn-secondary" disabled={disabled || !t.homed || !!blocked || target === ''} onClick={go}>Go</button>
          <button className="btn btn-secondary" disabled={disabled || !t.homed || !!blocked} onClick={() => run('park', visualApi.park)}
            title={`To the swap angle (${swap}°), torque off after`}>
            Park / swap {swap}°
          </button>
          {!t.homed && (
            <button className="btn btn-secondary" disabled={disabled || !!blocked} onClick={() => run('homing', () => visualApi.home())}
              title="Slowly into the hard stop: that is 0°">
              Home
            </button>
          )}
          <button className="btn btn-danger" disabled={!connected} onClick={() => run('torque off', visualApi.torqueOff)}>
            Torque off
          </button>
        </div>
        <div className="rig-row">
          <label><input type="checkbox" checked={showTower} onChange={() => toggle('showTower')} /> tower</label>
          <label><input type="checkbox" checked={camera} onChange={() => toggle('camera')} /> camera</label>
          <label><input type="checkbox" checked={overlay} disabled={!camera} onChange={() => toggle('overlay')} /> overlay</label>
        </div>
        <div className="dim">Slow moves, torque off at every stop. The plate waits for the hand, and the hand for the plate. E-STOP stops both.</div>
        {note && <div className="rig-note">{note}</div>}
      </div>
    </Panel>
  )
}

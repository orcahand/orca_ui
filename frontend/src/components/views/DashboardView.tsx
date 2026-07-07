// Capability-driven dashboard: tactile full-width, encoders + motors beneath.

import { useAppStore } from '../../state/appStore'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { MotorPanel } from '../motors/MotorPanel'
import { TactilePanel } from '../tactile/TactilePanel'

export function DashboardView() {
  const status = useAppStore((s) => s.status)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const caps = status?.capabilities

  if (!wsConnected) {
    return (
      <div className="detecting-card">
        <div className="big">BACKEND OFFLINE</div>
        <div>waiting for the orca-ui server…</div>
      </div>
    )
  }

  if (!caps) {
    return (
      <div className="detecting-card">
        <div className="big">SEARCHING FOR HARDWARE</div>
        <div>{status?.message ?? 'auto-detecting motor bus and sensors…'}</div>
        <div style={{ marginTop: 8, fontSize: 10 }}>
          connect the hand via USB — no button pressing required
        </div>
      </div>
    )
  }

  const twoColumns = caps.encoders && caps.motors

  return (
    <>
      {caps.tactile && <TactilePanel />}
      <div
        style={
          twoColumns
            ? {
                display: 'grid',
                gridTemplateColumns:
                  'repeat(auto-fit, minmax(480px, 1fr))',
                gap: 12,
                alignItems: 'start',
              }
            : undefined
        }
      >
        {caps.encoders && <EncoderPanel />}
        {caps.motors && <MotorPanel />}
      </div>
    </>
  )
}

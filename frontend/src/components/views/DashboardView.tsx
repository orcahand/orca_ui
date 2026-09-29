// The front page for every hand: the hand itself in 3D, what is connected,
// and one section per capability the session actually got. Nothing here is
// gated on the hand having sensors — a motors-only hand still has motors to
// show, and the health strip is the only place the console says how many of
// each device answered. The scene holds its place with no session at all
// (maintenance, released hardware) so the page never goes blank.

import { useAppStore } from '../../state/appStore'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { HealthSummary } from '../monitor/HealthSummary'
import { MotorPanel } from '../motors/MotorPanel'
import { TactilePanel } from '../tactile/TactilePanel'
import { TeleopStatusCard } from '../teleop/TeleopStatusCard'
import { CameraPreview } from '../teleop/CameraPreview'
import { HandScenePanel } from '../three/HandScenePanel'

export function DashboardView() {
  const caps = useAppStore((s) => s.status?.capabilities)

  return (
    <>
      <TeleopStatusCard />
      <HealthSummary />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: caps?.motors
            ? 'minmax(0, 1fr) 460px'
            : 'minmax(0, 1fr)',
          gap: 12,
          alignItems: 'start',
        }}
      >
        <HandScenePanel height="min(52vh, 560px)" />
        {/* CameraPreview self-hides unless a camera teleop session is live. */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {caps?.motors && <MotorPanel />}
          <CameraPreview />
        </div>
      </div>
      {caps?.tactile && <TactilePanel />}
      {caps?.encoders && <EncoderPanel />}
    </>
  )
}

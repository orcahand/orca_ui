// 3D tab: the hand scene at full window height, with the same motor panel as
// the dashboard beside it. The dashboard carries the same scene in a shorter
// box; this view exists for when the geometry is what you are studying.

import { useAppStore } from '../../state/appStore'
import { MotorPanel } from '../motors/MotorPanel'
import { CameraPreview } from '../teleop/CameraPreview'
import { HandScenePanel } from '../three/HandScenePanel'

export function ThreeDView() {
  const caps = useAppStore((s) => s.status?.capabilities)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: caps?.motors ? 'minmax(0, 1fr) 460px' : '1fr',
        gap: 12,
        alignItems: 'start',
      }}
    >
      <HandScenePanel height="calc(100vh - 240px)" />
      {/* CameraPreview self-hides unless a camera teleop session is live. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {caps?.motors && <MotorPanel />}
        <CameraPreview />
      </div>
    </div>
  )
}

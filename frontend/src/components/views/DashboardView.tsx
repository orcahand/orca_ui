// The front page for every hand: the hand itself in 3D, what is connected,
// and one section per capability the session actually got. Nothing here is
// gated on the hand having sensors — a motors-only hand still has motors to
// show, and the health strip is the only place the console says how many of
// each device answered. The scene holds its place with no session at all
// (maintenance, released hardware) so the page never goes blank.

import { useAppStore, useResearchUi } from '../../state/appStore'
import { LinkActions } from '../common/LinkActions'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { HealthSummary } from '../monitor/HealthSummary'
import { MotorPanel } from '../motors/MotorPanel'
import { TactilePanel } from '../tactile/TactilePanel'
import { TeleopStatusCard } from '../teleop/TeleopStatusCard'
import { CameraPreview } from '../teleop/CameraPreview'
import { HandScenePanel } from '../three/HandScenePanel'
import { StudyCalibrationPanel } from '../visual/StudyCalibrationPanel'
import { RigCamera } from '../rig/RigCamera'
import { RigPanel } from '../rig/RigPanel'
import { useRigPolling } from '../../state/rigStore'

export function DashboardView() {
  const status = useAppStore((s) => s.status)
  const caps = status?.capabilities
  const missing = status?.missing ?? []
  // Bare motor mode has no hand: the 3D scene would render a whole right hand
  // for a motor lying on the bench, and the pseudo-joints match none of its
  // links. The motors are the page.
  const bare = status?.bare ?? false
  const research = useResearchUi()
  // The calibration rig, when orca-ui found it: drawn around the hand, its controls beside.
  useRigPolling()

  return (
    <>
      <TeleopStatusCard />
      {/* Always rendered: with no session the health strip below is empty and
          this is the only way back without leaving the page. */}
      <section
        className="panel"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          fontSize: 10,
          padding: '6px 12px',
        }}
      >
        <span style={{ color: 'var(--dim)' }}>
          {!caps
            ? 'no session'
            : missing.length > 0
              ? `${missing.join(' + ')} declared but not connected`
              : status?.message || 'link'}
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <LinkActions />
        </span>
      </section>
      <HealthSummary />
      {bare ? (
        caps?.motors && <MotorPanel />
      ) : (
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
          {/* The 3D view stays put while the right column scrolls, to compare mappings instantly. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, position: 'sticky', top: 8 }}>
            <HandScenePanel height="min(52vh, 560px)" withRig />
            <RigCamera />
          </div>
          {/* CameraPreview self-hides unless a camera teleop session is live. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {caps?.motors && research && <StudyCalibrationPanel />}
            <RigPanel />
            {caps?.motors && <MotorPanel />}
            <CameraPreview />
          </div>
        </div>
      )}
      {caps?.tactile && <TactilePanel />}
      {caps?.encoders && <EncoderPanel />}
    </>
  )
}

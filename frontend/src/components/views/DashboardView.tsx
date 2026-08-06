// Capability-driven dashboard: tactile full-width, encoders + motors beneath.
// Pre-session states never reach here — App renders the BootHero instead.

import { useAppStore } from '../../state/appStore'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { EncoderUnavailableCard } from '../encoders/EncoderUnavailableCard'
import { MotorPanel } from '../motors/MotorPanel'
import { TactilePanel } from '../tactile/TactilePanel'
import { TeleopStatusCard } from '../teleop/TeleopStatusCard'

export function DashboardView() {
  const status = useAppStore((s) => s.status)
  const caps = status?.capabilities

  // Maintenance closes the session (capabilities go null) — the banner above
  // the view says why; there's nothing live to draw.
  if (!caps) return null

  // A declared-but-missing encoder tier still occupies its column — the
  // placeholder explains the absence in situ rather than leaving a gap.
  const encoderSlot = caps.encoders || Boolean(caps.declared.encoders)
  const twoColumns = encoderSlot && caps.motors

  return (
    <>
      <TeleopStatusCard />
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
        {caps.encoders ? (
          <EncoderPanel />
        ) : (
          encoderSlot && <EncoderUnavailableCard />
        )}
        {caps.motors && <MotorPanel />}
      </div>
    </>
  )
}

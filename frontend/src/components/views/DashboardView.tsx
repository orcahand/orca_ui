// Capability-driven dashboard: tactile full-width, encoders + motors beneath.
// Pre-session states never reach here — App renders the BootHero instead.

import { useAppStore } from '../../state/appStore'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { MotorPanel } from '../motors/MotorPanel'
import { TactilePanel } from '../tactile/TactilePanel'

export function DashboardView() {
  const status = useAppStore((s) => s.status)
  const caps = status?.capabilities

  // Maintenance closes the session (capabilities go null) — the banner above
  // the view says why; there's nothing live to draw.
  if (!caps) return null

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

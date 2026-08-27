// The one main view: electrical health strip, then the 3D scene with the
// motor controls beside it (the only Motor Control panel — the old separate
// 3D tab is merged in here), encoders, and the tactile sensors at the
// bottom. Pre-session states never reach here — App renders the BootHero.

import { lazy, Suspense } from 'react'
import { useAppStore } from '../../state/appStore'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { EncoderUnavailableCard } from '../encoders/EncoderUnavailableCard'
import { HealthSummary } from '../monitor/HealthSummary'
import { TactilePanel } from '../tactile/TactilePanel'
import { TeleopStatusCard } from '../teleop/TeleopStatusCard'

// three.js only loads when the dashboard first renders, not with the shell.
const SceneBlock = lazy(() =>
  import('./ThreeDView').then((m) => ({ default: m.ThreeDView })),
)

export function DashboardView() {
  const status = useAppStore((s) => s.status)
  const caps = status?.capabilities

  // Maintenance closes the session (capabilities go null) — the banner above
  // the view says why; there's nothing live to draw.
  if (!caps) return null

  // A declared-but-missing encoder tier still gets a card — the placeholder
  // explains the absence in situ rather than leaving a gap.
  const encoderSlot = caps.encoders || Boolean(caps.declared.encoders)

  return (
    <>
      <TeleopStatusCard />
      <HealthSummary />
      <Suspense
        fallback={<div className="detecting-card">loading 3D view…</div>}
      >
        <SceneBlock />
      </Suspense>
      {caps.encoders ? (
        <EncoderPanel />
      ) : (
        encoderSlot && <EncoderUnavailableCard />
      )}
      {caps.tactile && <TactilePanel />}
    </>
  )
}

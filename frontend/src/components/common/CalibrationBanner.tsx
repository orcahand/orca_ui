// Slim banner shown on the observe-and-drive views when the hand declares
// joint encoders but came up without them because it isn't calibrated. The
// connect ladder drops to a non-feedback tier in that case, which silently
// takes the encoder panel, joint glow, motor ghost and pose capture with it —
// this is the one place that says why, and how to fix it.

import { useAppStore } from '../../state/appStore'

export function CalibrationBanner() {
  const caps = useAppStore((s) => s.status?.capabilities ?? null)
  const calibration = useAppStore((s) => s.handInfo?.calibration ?? null)
  const setView = useAppStore((s) => s.setView)

  // Only when calibration is the reason: a hand with no encoders at all is
  // not degraded, and encoders lost to a hardware fault need a different fix.
  const blocked =
    caps !== null &&
    Boolean(caps.declared.encoders) &&
    !caps.encoders &&
    calibration?.needs_calibration === true
  if (!blocked) return null

  return (
    <div className="maintenance-banner">
      JOINT SENSING OFF — {calibration?.hint ?? 'the hand is not calibrated'}
      <button className="banner-cta" onClick={() => setView('setup')}>
        Calibrate the hand
      </button>
    </div>
  )
}

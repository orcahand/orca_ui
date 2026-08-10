// One line at the top of the Setup tab answering "what should I do here?".
// Same source as the CalibrationBanner (hand info), but phrased as the next
// action rather than as a warning, because on this tab the fix is right below.

import type { ReactNode } from 'react'
import { useAppStore } from '../../state/appStore'

export function SetupStatus() {
  const calibration = useAppStore((s) => s.handInfo?.calibration ?? null)
  const caps = useAppStore((s) => s.status?.capabilities ?? null)
  // null: no motor session, so there is nothing to report — the cards below
  // carry their own blocked reason.
  if (!calibration || calibration.motors === null) return null

  if (!calibration.motors) {
    return (
      <Strip tone="warn">
        <strong>This hand has not been calibrated yet.</strong> Start with the
        full setup below — it takes you through tensioning and calibration
        together.
      </Strip>
    )
  }

  const missing = calibration.missing_anchors
  if (missing.length > 0) {
    const shown = missing.slice(0, 4).join(', ')
    return (
      <Strip tone="warn">
        <strong>
          {missing.length} joint{missing.length > 1 ? 's' : ''} still
          uncalibrated
        </strong>{' '}
        ({shown}
        {missing.length > 4 ? `, +${missing.length - 4} more` : ''}) — the hand
        cannot read where they are until you calibrate them.
      </Strip>
    )
  }

  // Calibration is complete, yet the hand came up without the joint encoders
  // it declares. Calibrating again cannot fix that, so do not let the strip
  // say "ready" while the header says degraded.
  if (caps !== null && Boolean(caps.declared.encoders) && !caps.encoders) {
    return (
      <Strip tone="warn">
        <strong>Calibrated, but joint sensing is off.</strong> The encoder
        stream did not come up when the hand connected, and calibrating again
        will not change that. Reconnect from the Motors tab to try again.
      </Strip>
    )
  }

  return (
    <Strip tone="ok">
      <strong>The hand is calibrated and ready.</strong> Come back here to
      re-tension and re-calibrate once the fingers start to feel loose.
    </Strip>
  )
}

function Strip({
  tone,
  children,
}: {
  tone: 'ok' | 'warn'
  children: ReactNode
}) {
  return (
    <div className={`setup-status ${tone}`}>
      <span className="setup-status-dot" />
      <span className="setup-status-text">{children}</span>
    </div>
  )
}

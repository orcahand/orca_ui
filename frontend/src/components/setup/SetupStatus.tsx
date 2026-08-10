// One line at the top of the Setup tab answering "what should I do here?".
// Same source as the CalibrationBanner (hand info), but phrased as the next
// action rather than as a warning, because on this tab the fix is right below.

import type { ReactNode } from 'react'
import { useAppStore } from '../../state/appStore'

export function SetupStatus() {
  const calibration = useAppStore((s) => s.handInfo?.calibration ?? null)
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

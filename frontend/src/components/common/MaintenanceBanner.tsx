// Slim banner shown on the observe-and-drive views while the supervisor has
// lent the hardware to a maintenance operation (calibrate/tension/wizard),
// and while it takes it back afterwards. That hand-back rebuilds the session,
// which otherwise looks like the hand dropping out.

import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'

export function MaintenanceBanner() {
  const maintenance = useAppStore((s) => s.status?.state === 'maintenance')
  const leaving = useAppStore((s) => s.status?.leaving_maintenance ?? false)
  const detail = useOperationStore(
    (s) => s.operation?.detail ?? s.operation?.phase ?? s.operation?.kind ?? null,
  )
  if (leaving) {
    return (
      <div className="maintenance-banner">
        LEAVING MAINTENANCE — reconnecting the hand
      </div>
    )
  }
  if (!maintenance) return null
  return (
    <div className="maintenance-banner">
      HAND IN MAINTENANCE{detail ? ` — ${detail}` : ''}
    </div>
  )
}

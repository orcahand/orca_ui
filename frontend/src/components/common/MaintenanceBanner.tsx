// Slim banner shown on the observe-and-drive views while the supervisor has
// lent the hardware to a maintenance operation (calibrate/tension/wizard).

import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'

export function MaintenanceBanner() {
  const maintenance = useAppStore((s) => s.status?.state === 'maintenance')
  const detail = useOperationStore(
    (s) => s.operation?.detail ?? s.operation?.phase ?? s.operation?.kind ?? null,
  )
  if (!maintenance) return null
  return (
    <div className="maintenance-banner">
      HAND IN MAINTENANCE{detail ? ` — ${detail}` : ''}
    </div>
  )
}

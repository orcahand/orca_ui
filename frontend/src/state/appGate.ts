// Gate for the app Engage button (session bar and session panel), built on
// the general control gate. The backend re-validates everything; this exists
// so the button says why it is disabled.

import { useAppSessionStore } from './appSessionStore'
import { useAppStore } from './appStore'
import { useControlGate } from './operationStore'

export function useEngageGate(): { allowed: boolean; reason: string | null } {
  const session = useAppSessionStore((s) => s.session)
  const control = useControlGate()
  const caps = useAppStore((s) => s.status?.capabilities)
  const torque = useAppStore((s) => s.control?.torque_enabled ?? false)

  if (!session || session.state !== 'preview') {
    return { allowed: false, reason: 'start the app first' }
  }
  if (!control.manualAllowed) return { allowed: false, reason: control.reason }
  if (!caps?.motors) return { allowed: false, reason: 'motor bus unavailable' }
  if (!torque) return { allowed: false, reason: 'enable torque to engage' }
  return { allowed: true, reason: null }
}

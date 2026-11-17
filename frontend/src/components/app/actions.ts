// Session actions shared by the session bar and the session panel. The
// backend validates everything; failures land in the error banner.

import { api } from '../../api/rest'
import type { AppSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

// Each names the session on screen, so a stale tab can't act on a newer one.
export const engage = (session: AppSnapshot) =>
  void api.appEngage(session.session_id).catch(fail)
export const disengage = (session: AppSnapshot) =>
  void api.appDisengage(session.session_id).catch(fail)
export const stop = (session: AppSnapshot) =>
  void api.appStop(session.session_id).catch(fail)
export const enableTorque = () => void api.torqueEnable().catch(fail)
export { fail }

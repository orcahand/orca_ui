// Session actions shared by the session bar and the session panel. The
// backend validates everything; failures land in the error banner.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export const engage = () => void api.appEngage().catch(fail)
export const disengage = () => void api.appDisengage().catch(fail)
export const stop = () => void api.appStop().catch(fail)
export const enableTorque = () => void api.torqueEnable().catch(fail)
export { fail }

// The saved tension sweeps and which one is the reference.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { TensionSweeps } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { failToBanner } from './setupUtils'

export function useSweeps(reload: unknown = null) {
  const [state, setState] = useState<TensionSweeps | null>(null)
  const refresh = useCallback(() => {
    api.sweeps().then(setState).catch(failToBanner)
    api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
  }, [])
  const modelName = useAppStore((s) => s.handInfo?.model_name)
  useEffect(() => refresh(), [refresh, modelName, reload])
  return { state, refresh }
}

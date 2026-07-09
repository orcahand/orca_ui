// Live operation log: the seq-merged cumulative buffer from operationStore.

import { useOperationStore } from '../../state/operationStore'
import { LogPane } from '../common/LogPane'

export function OperationLogPane() {
  const lines = useOperationStore((s) => s.logLines)
  return (
    <LogPane
      title="Operation Log"
      lines={lines}
      emptyText="no operation output yet — tension, calibrate, and wizard
          progress streams here"
    />
  )
}

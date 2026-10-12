// The one place tensioning dialogs are mounted: whichever tension operation is
// running gets its dialog, whoever started it, and stays readable after it
// ends until closed. The hold dialog can also be opened before its operation
// exists, to explain the step before any current flows.

import { useEffect, useState } from 'react'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { useTensionFlow } from '../../state/tensionFlow'
import { GuidedTensionDialog } from './GuidedTensionDialog'
import { HoldTensionDialog } from './HoldTensionDialog'

export function TensionDialogs() {
  const operation = useOperationStore((s) => s.operation)
  const holdOpen = useTensionFlow((s) => s.holdOpen)
  const closeHold = useTensionFlow((s) => s.closeHold)
  const dismissed = useTensionFlow((s) => s.dismissed)
  const dismiss = useTensionFlow((s) => s.dismiss)
  const [watched, setWatched] = useState<string | null>(null)

  const tension =
    operation?.kind === 'guided_tension' || operation?.kind === 'tension' ? operation : null
  const active = tension !== null && isOperationActive(tension)
  useEffect(() => {
    if (active) setWatched(tension.run_id)
  }, [active, tension?.run_id])

  const shown =
    tension && tension.run_id !== dismissed && (active || tension.run_id === watched)
      ? tension
      : null
  const close = () => {
    if (shown) dismiss(shown.run_id)
    closeHold()
  }

  if (shown?.kind === 'guided_tension') {
    return <GuidedTensionDialog operation={shown} onClose={close} />
  }
  if (shown?.kind === 'tension') return <HoldTensionDialog operation={shown} onClose={close} />
  if (holdOpen) return <HoldTensionDialog operation={null} onClose={closeHold} />
  return null
}

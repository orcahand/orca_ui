// Spooling tab: attaching the tendons while the hand is being built. One
// card runs the operation and mirrors its per-motor state; the log below it
// is the same operation log the Setup tab shows.

import { OperationLogPane } from '../setup/OperationLogPane'
import { SpoolingCard } from '../setup/SpoolingCard'

export function SpoolingView() {
  return (
    <>
      <SpoolingCard />
      <OperationLogPane />
    </>
  )
}

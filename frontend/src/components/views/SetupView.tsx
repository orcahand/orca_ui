// Setup tab: hand lifecycle operations — tension, calibrate (full or a
// joint subset), the guided bring-up wizard — plus the live operation log.
// Cross-tab control of a running operation lives in the TransportBar; these
// cards start operations and mirror their state in place.

import { CalibrateCard } from '../setup/CalibrateCard'
import { OperationLogPane } from '../setup/OperationLogPane'
import { TensionCard } from '../setup/TensionCard'
import { WizardCard } from '../setup/WizardCard'

export function SetupView() {
  return (
    <>
      <div className="setup-grid">
        <TensionCard />
        <CalibrateCard />
        <WizardCard />
      </div>
      <OperationLogPane />
    </>
  )
}

// Setup tab: getting a hand ready to use. The full setup leads — it is what
// a new hand needs and what most people should run — and tension/calibrate sit
// under it as the same two things on their own, for when only one is needed.
// Cross-tab control of a running operation lives in the TransportBar; these
// cards start operations and mirror their state in place.

import { CalibrateCard } from '../setup/CalibrateCard'
import { FullSetupCard } from '../setup/FullSetupCard'
import { OperationLogPane } from '../setup/OperationLogPane'
import { SetupStatus } from '../setup/SetupStatus'
import { TensionCard } from '../setup/TensionCard'

export function SetupView() {
  return (
    <>
      <SetupStatus />
      <FullSetupCard />
      <div className="setup-section">
        <span className="setup-section-title">Single steps</span>
        <span className="setup-section-note">
          the same two things on their own — for a hand that is already set up
        </span>
        <span className="setup-section-rule" />
      </div>
      <div className="setup-grid">
        <TensionCard />
        <CalibrateCard />
      </div>
      <OperationLogPane />
    </>
  )
}

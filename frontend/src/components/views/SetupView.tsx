// Placeholder — M5 fills this with the tension/calibrate/wizard cards and
// the live operation log pane.

import { Panel } from '../common/Panel'

export function SetupView() {
  return (
    <Panel title="Setup">
      <div className="detecting-card">
        <div className="big">SETUP</div>
        <div>tension · calibrate · guided bring-up wizard</div>
        <div style={{ marginTop: 8, fontSize: 10 }}>coming in M5</div>
      </div>
    </Panel>
  )
}

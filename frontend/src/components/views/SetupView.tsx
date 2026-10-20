// Setup tab: tension → calibrate → run-in, plus fingertip numbering under
// Advanced. Each step can run on its own; the flow only marks which one is next.
// Cross-tab control of a running operation lives in the TransportBar.

import { useState } from 'react'
import { useAppStore } from '../../state/appStore'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { HardwareVersionPrompt } from '../header/HardwareVersion'
import { CalibrateStep } from '../setup/CalibrateStep'
import { FingertipMismatches, FingertipNumbering } from '../setup/FingertipNumbering'
import type { StepState } from '../setup/FlowStep'
import { OperationLogPane } from '../setup/OperationLogPane'
import { RunInStep } from '../setup/RunInStep'
import { readRunInDone, runInCompleted } from '../setup/setupUtils'
import { TensionStep } from '../setup/TensionStep'

// Remembered across reloads and the view remounting when the hand reconnects.
const ADVANCED_KEY = 'orca-ui.setup-advanced'

export function SetupView() {
  const handInfo = useAppStore((s) => s.handInfo)
  const caps = useAppStore((s) => s.status?.capabilities ?? null)
  const operation = useOperationStore((s) => s.operation)

  const last = handInfo?.last_tension ?? null
  const progress = handInfo?.tension_progress ?? null
  const tensioned =
    last !== null && (progress === null || progress.updated_at <= last.completed_at)
  const calibration = handInfo?.calibration
  const calibrated =
    calibration?.motors === true && calibration.missing_anchors.length === 0
  const ranIn = readRunInDone(handInfo?.model_name) !== null || runInCompleted(operation)

  const tension: StepState = tensioned ? 'done' : 'next'
  const calibrate: StepState = calibrated ? 'done' : tensioned ? 'next' : 'todo'
  const runIn: StepState = !calibrated
    ? 'todo'
    : ranIn
      ? 'done'
      : tensioned
        ? 'next'
        : 'todo'

  const encodersOff =
    calibrated && caps !== null && Boolean(caps.declared.encoders) && !caps.encoders

  // Only hands that carry fingertips get numbering; capabilities are blank
  // while the numbering op holds the hand in maintenance, so keep it then.
  const numbering = operation?.kind === 'number_fingertip' && isOperationActive(operation)
  const tactileHand = Boolean(caps?.declared.tactile ?? caps?.tactile) || numbering
  const [advancedOpen, setAdvancedOpen] = useState(
    () => numbering || localStorage.getItem(ADVANCED_KEY) === 'true',
  )

  return (
    <>
      {caps !== null && !caps.motors && (
        <div className="flow-info warn">⚠ motor bus unavailable</div>
      )}
      {encodersOff && (
        <div className="flow-info warn" title="Reconnect from the Motors tab">
          ⚠ joint sensing off · reconnect
        </div>
      )}
      <FingertipMismatches mismatches={handInfo?.fingertips?.mismatches} />
      <HardwareVersionPrompt />
      <div className="flow">
        <TensionStep state={tension} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <CalibrateStep state={calibrate} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <RunInStep state={runIn} calibrated={calibrated} />
      </div>
      {tactileHand && (
        <details
          className="flow-advanced setup-advanced"
          open={advancedOpen}
          onToggle={(e) => {
            const open = e.currentTarget.open
            localStorage.setItem(ADVANCED_KEY, String(open))
            setAdvancedOpen(open)
          }}
        >
          <summary>Advanced</summary>
          <FingertipNumbering />
        </details>
      )}
      <OperationLogPane />
    </>
  )
}

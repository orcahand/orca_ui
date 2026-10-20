// Setup tab: tension → calibrate → run-in. Each step can run on its own; the
// flow only marks which one is next. Cross-tab control of a running operation
// lives in the TransportBar.

import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'
import { HardwareVersionPrompt } from '../header/HardwareVersion'
import { CalibrateStep } from '../setup/CalibrateStep'
import type { StepState } from '../setup/FlowStep'
import { OperationLogPane } from '../setup/OperationLogPane'
import { RunInStep } from '../setup/RunInStep'
import { readRunInDone, runInCompleted } from '../setup/setupUtils'
import { TensionStep } from '../setup/TensionStep'

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
      <HardwareVersionPrompt />
      <div className="flow">
        <TensionStep state={tension} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <CalibrateStep state={calibrate} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <RunInStep state={runIn} calibrated={calibrated} />
      </div>
      <OperationLogPane />
    </>
  )
}

// Setup tab: tension → calibrate → run. Each step can run on its own; the
// flow only marks which one is next. Cross-tab control of a running operation
// lives in the TransportBar. The flowchart under the steps spells the loop
// out; the operation log sits collapsed at the bottom.

import { useAppStore } from '../../state/appStore'
import { useOperationStore } from '../../state/operationStore'
import { useSetupVariant } from '../../state/setupVariant'
import { HardwareVersionPrompt } from '../header/HardwareVersion'
import { CalibrateStep } from '../setup/CalibrateStep'
import type { StepState } from '../setup/FlowStep'
import { OperationLogPane } from '../setup/OperationLogPane'
import { RunInStep } from '../setup/RunInStep'
import { readRunInDone, runInCompleted } from '../setup/setupUtils'
import { TensionStep } from '../setup/TensionStep'
import { WorkflowChart } from '../setup/WorkflowChart'

export function SetupView() {
  const handInfo = useAppStore((s) => s.handInfo)
  const caps = useAppStore((s) => s.status?.capabilities ?? null)
  const operation = useOperationStore((s) => s.operation)
  const variant = useSetupVariant((s) => s.variant)

  const last = handInfo?.last_tension ?? null
  const progress =
    (variant === 'kai' ? handInfo?.tension_progress_slack : handInfo?.tension_progress) ?? null
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
        <TensionStep state={tension} variant={variant} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <CalibrateStep state={calibrate} variant={variant} />
        <span className="flow-arrow" aria-hidden="true">›</span>
        <RunInStep state={runIn} calibrated={calibrated} />
      </div>
      <WorkflowChart />
      <details className="log-collapse">
        <summary>Operation log</summary>
        <OperationLogPane />
      </details>
    </>
  )
}

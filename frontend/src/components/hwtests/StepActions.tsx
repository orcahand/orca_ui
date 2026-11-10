// A step's console action: `operation:<name>` starts that operation through the
// Setup tab's own start paths (its dialog opens globally), and `jog:<joints>`
// offers buttons that bend those joints through the joint command path.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { sendTarget } from '../../state/commandBus'
import {
  isOperationActive,
  operationLabel,
  useControlGate,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { latest } from '../../state/streamStore'
import { startGuidedTension, startSlackTest } from '../setup/probeStart'
import { failToBanner } from '../setup/setupUtils'

interface OperationAction {
  label: string
  start: () => Promise<unknown>
}

const OPERATIONS: Record<string, OperationAction> = {
  slack_test: { label: 'Start slack test', start: () => startSlackTest() },
  guided_tension: { label: 'Start guided tensioning', start: () => startGuidedTension() },
  calibrate_manual: {
    label: 'Start manual calibration',
    start: () =>
      api.operationStart('calibrate', { joints: null, force_wrist: false, manual: true }),
  },
}

const JOG_FRACTION = 0.7
const JOG_RAMP_MS = 800

const ramps = new Map<string, number>()

// Moves the joint's setpoint smoothly, one target per frame like the sliders do.
function rampJoint(joint: string, to: number): void {
  const from =
    latest.joints.target[joint] ??
    latest.joints.measured[joint] ??
    latest.joints.estimate[joint] ??
    to
  const previous = ramps.get(joint)
  if (previous !== undefined) cancelAnimationFrame(previous)
  const t0 = performance.now()
  const step = () => {
    const f = Math.min(1, (performance.now() - t0) / JOG_RAMP_MS)
    sendTarget(joint, from + (to - from) * f)
    if (f < 1) ramps.set(joint, requestAnimationFrame(step))
    else ramps.delete(joint)
  }
  ramps.set(joint, requestAnimationFrame(step))
}

function OperationButton({ name }: { name: string }) {
  const gate = useStartGate('motors')
  const operation = useOperationStore((s) => s.operation)
  const guidedSupported = useAppStore((s) => s.handInfo?.guided_tension !== false)
  const action = OPERATIONS[name]
  const active = isOperationActive(operation) ? operation : null

  if (!action) {
    return (
      <div className="hwt-hint warn">
        This step asks for the console operation “{name}”, which the Tests tab cannot start. Start
        it from the Setup tab.
      </div>
    )
  }
  const unsupported =
    name === 'guided_tension' && !guidedSupported
      ? 'the installed orca_core has no guided tensioning'
      : null
  const blocked = gate.blocked || unsupported !== null
  return (
    <div className="hwt-action">
      <button
        className="btn btn-primary"
        disabled={blocked}
        title={unsupported ?? gate.reason ?? undefined}
        onClick={() => void action.start().catch(failToBanner)}
      >
        {action.label}
      </button>
      {blocked && <span className="hwt-hint warn">{unsupported ?? gate.reason}</span>}
      {active && (
        <span className="hwt-op-state">
          <strong>{operationLabel(active.kind)}</strong> {active.state}
          {active.phase ? ` · ${active.phase}` : ''}
          {active.detail ? ` · ${active.detail}` : ''}
          {active.progress !== null ? ` · ${Math.round(active.progress * 100)}%` : ''}
          {active.awaiting && <em> · waiting for you in its dialog</em>}
          <button
            className="btn btn-danger"
            onClick={() => void api.operationStop().catch(failToBanner)}
          >
            Stop
          </button>
        </span>
      )}
      {!active && operation && (
        <span className="hwt-hint">
          last: {operationLabel(operation.kind)} {operation.state}
          {operation.error ? ` · ${operation.error}` : ''}
        </span>
      )}
    </div>
  )
}

function JogButtons({ joints }: { joints: string[] }) {
  const infos = useAppStore((s) => s.handInfo?.joints ?? null)
  const torque = useAppStore((s) => s.status?.torque_enabled ?? false)
  const gate = useControlGate()

  if (!infos)
    return <div className="hwt-hint warn">No hand session: jogging needs a connected hand.</div>
  const disabled = !torque || !gate.manualAllowed
  return (
    <div className="hwt-jog">
      {!torque && (
        <div className="hwt-action">
          <span className="hwt-hint warn">Torque is off: the joints cannot move.</span>
          <button
            className="btn btn-primary"
            onClick={() => void api.torqueEnable().catch(failToBanner)}
          >
            Torque on
          </button>
        </div>
      )}
      {!gate.manualAllowed && <div className="hwt-hint warn">{gate.reason}</div>}
      {joints.map((id) => {
        const info = infos.find((joint) => joint.id === id)
        if (!info) {
          return (
            <div key={id} className="hwt-hint warn">
              {id}: not a joint of this hand
            </div>
          )
        }
        const [low, high] = info.rom
        const toLow = info.neutral + (low - info.neutral) * JOG_FRACTION
        const toHigh = info.neutral + (high - info.neutral) * JOG_FRACTION
        return (
          <div key={id} className="hwt-jog-row">
            <span className="hwt-jog-joint">{id}</span>
            <button
              className="btn btn-secondary"
              disabled={disabled}
              onClick={() => rampJoint(id, toLow)}
            >
              − to {toLow.toFixed(0)}°
            </button>
            <button
              className="btn btn-secondary"
              disabled={disabled}
              onClick={() => rampJoint(id, info.neutral)}
            >
              neutral {info.neutral.toFixed(0)}°
            </button>
            <button
              className="btn btn-secondary"
              disabled={disabled}
              onClick={() => rampJoint(id, toHigh)}
            >
              + to {toHigh.toFixed(0)}°
            </button>
            <span className="hwt-hint">
              ROM {low.toFixed(0)}° … {high.toFixed(0)}°
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function StepActions({ action }: { action: string | null }) {
  if (!action) return null
  const [kind, ...rest] = action.split(':')
  const arg = rest.join(':').trim()
  if (kind === 'operation') return <OperationButton name={arg} />
  if (kind === 'jog') {
    const joints = arg
      .split(',')
      .map((joint) => joint.trim())
      .filter(Boolean)
    return <JogButtons joints={joints} />
  }
  return <div className="hwt-hint warn">Unknown action “{action}”: do it by hand as described.</div>
}

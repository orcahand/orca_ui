// Motor-chain configuration (orca_core's configure_motor_chain workflow):
// guided per-motor ID'ing during assembly, visualized as the daisy chain
// hanging off the OH board. Factory reset is deliberately behind a two-step
// confirmation — resetting means redoing the whole ID'ing process.
//
// Runs as a maintenance operation, so it works with NO hand connected
// (assembly time); the transport bar carries progress/stop on every tab.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { MotorChainExtra, OperationSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
} from '../../state/operationStore'
import { isTeleopEngaged, useTeleopStore } from '../../state/teleopStore'
import { Panel } from '../common/Panel'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

function chainExtra(op: OperationSnapshot | null): MotorChainExtra | null {
  if (!op || op.kind !== 'configure_chain' || !op.extra) return null
  return op.extra as unknown as MotorChainExtra
}

export function MotorChainPanel() {
  const operation = useOperationStore((s) => s.operation)
  const teleopEngaged = useTeleopStore((s) => isTeleopEngaged(s.session))
  const [confirmingReset, setConfirmingReset] = useState(false)

  const anyOpActive = isOperationActive(operation)
  const chainOp =
    operation?.kind === 'configure_chain' ? operation : null
  const chainActive = chainOp !== null && isOperationActive(chainOp)
  const extra = chainExtra(chainOp)

  const startBlocked = anyOpActive || teleopEngaged
  const startReason = anyOpActive
    ? `${operation!.kind} is running — stop it first`
    : teleopEngaged
      ? 'teleop is engaged — disengage first'
      : null

  // An armed confirmation must not survive a state change: if an operation
  // starts (or teleop engages) while "Yes, reset" sits on screen, the next
  // click after it clears would fire the destructive reset with one click.
  useEffect(() => {
    if (startBlocked) setConfirmingReset(false)
  }, [startBlocked])

  const startConfigure = () => {
    setConfirmingReset(false)
    void api
      .operationStart('configure_chain', { mode: 'configure' })
      .catch(fail)
  }

  const startReset = () => {
    setConfirmingReset(false)
    void api
      .operationStart('configure_chain', { mode: 'reset', confirm: true })
      .catch(fail)
  }

  const toolbar = chainActive ? (
    <button
      className="btn btn-danger"
      title="stop the chain operation"
      onClick={() => void api.operationStop().catch(fail)}
    >
      ■ stop
    </button>
  ) : undefined

  return (
    <Panel title="Motor Chain" toolbar={toolbar}>
      <p className="setup-card-hint" style={{ marginBottom: 10 }}>
        Assembly-time motor ID'ing: fresh motors ship at factory defaults and
        are programmed one at a time as you build the daisy chain (highest ID
        at the board, wrist last).
      </p>

      {extra && <ChainFlow extra={extra} />}

      {chainActive && chainOp && (
        <div className="chain-instruction">
          {chainOp.detail ?? chainOp.phase ?? 'working…'}
        </div>
      )}
      {!chainActive && chainOp?.state === 'done' && (
        <div className="chain-instruction done">
          ✓ {chainOp.detail ?? 'done'}
        </div>
      )}
      {!chainActive && chainOp?.state === 'error' && (
        <div className="chain-instruction error">
          ✕ {chainOp.error ?? 'failed'}
        </div>
      )}

      {!chainActive && (
        <div className="setup-card-row" style={{ marginTop: 10 }}>
          <button
            className="btn btn-primary"
            disabled={startBlocked}
            title={startReason ?? 'start the guided per-motor configuration'}
            onClick={startConfigure}
          >
            ⚙ Configure chain
          </button>
          {!confirmingReset ? (
            <button
              className="btn btn-secondary"
              disabled={startBlocked}
              title={
                startReason ??
                'revert motors to factory defaults (asks for confirmation)'
              }
              onClick={() => setConfirmingReset(true)}
            >
              Reset to factory…
            </button>
          ) : (
            <div className="chain-confirm">
              <span className="chain-confirm-text">
                ⚠ Really reset? Every motor found on the bus is reverted to
                factory ID 1 — you will have to redo the whole ID'ing
                process, motor by motor.
              </span>
              <button
                className="btn btn-danger"
                disabled={startBlocked}
                onClick={startReset}
              >
                Yes, reset the motors
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setConfirmingReset(false)}
              >
                Cancel
              </button>
            </div>
          )}
          {startBlocked && (
            <span className="setup-card-reason">{startReason}</span>
          )}
        </div>
      )}
    </Panel>
  )
}

// ----- chain visualization -----------------------------------------------------

const STATE_GLYPH: Record<string, string> = {
  configured: '✓',
  expected: '▶',
  invalid: '✕',
  reset: '↺',
  pending: '·',
}

function ChainFlow({ extra }: { extra: MotorChainExtra }) {
  return (
    <div className="chain-flow">
      <div className="chain-node board">
        <span className="chain-node-id">OH</span>
        <span className="chain-node-model">board</span>
      </div>
      {extra.chain.map((slot) => (
        <div key={slot.id} style={{ display: 'contents' }}>
          <span className="chain-arrow">→</span>
          <div
            className={`chain-node ${slot.state}${
              slot.role === 'wrist' ? ' wrist' : ''
            }`}
            title={`${slot.model} (${slot.role}) — ${slot.state}`}
          >
            <span className="chain-node-id">
              {STATE_GLYPH[slot.state] ?? ''} {slot.id}
            </span>
            <span className="chain-node-model">{slot.model}</span>
          </div>
        </div>
      ))}
      <span className="chain-meta">
        {extra.motor_type} @ {extra.target_baud.toLocaleString()} bps
        {extra.mode === 'reset' &&
          ` · reset mode (${extra.resets.length} reset)`}
      </span>
    </div>
  )
}

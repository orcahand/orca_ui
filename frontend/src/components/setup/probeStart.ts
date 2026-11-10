// Starting a measurement right after another maintenance operation: the hand
// is still reconnecting for a moment, so the start is retried until it takes.

import { api } from '../../api/rest'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { estopsFired } from '../../state/estop'
import { useSetupVariant } from '../../state/setupVariant'
import { DEFAULT_OFFSET_DEG } from '../../state/tensionFlow'
import { loadPassFractions, loadPassSlack } from './guidedSettings'

export const SLACK_HINT =
  'Slack test: you hold one joint at a time while its motor winds each way at low current. The free rotation is the slack; more than half a turn fails the joint and blocks calibration.'
export const SWEEP_HINT =
  'Tension sweep: the fingers together per joint kind, then each thumb joint, are driven slowly from one calibrated limit to the other and back while the current is recorded; friction and static load along the travel are compared with the reference curves. Needs a calibrated hand. Keep clear.'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function startSlackTest(params: Record<string, unknown> = {}): Promise<void> {
  return startWhenConnected('slack_test', params)
}

// One pass limit to limit and back per joint.
export async function startTensionSweep(params: Record<string, unknown> = {}): Promise<void> {
  return startWhenConnected('tension_sweep', { repeats: 1, ...params })
}

// Every finger motor turned the default pull counterclockwise and held while the
// operator ratchets (the hold dialog's run, without winding first).
export async function startHoldTension(): Promise<void> {
  return startWhenConnected('tension', { move_motors: false, offset_deg: DEFAULT_OFFSET_DEG })
}

// Guided tensioning (v2.1 hands) with the page's scoring; the currents come
// from the hand's family defaults unless the Tension step passed its own.
export async function startGuidedTension(params: Record<string, unknown> = {}): Promise<void> {
  const kai = useSetupVariant.getState().variant === 'kai'
  return startWhenConnected('guided_tension', {
    tension_offset_deg: DEFAULT_OFFSET_DEG,
    ...(kai ? { scoring: 'slack', pass_slack_deg: loadPassSlack() } : { scoring: 'fraction', pass_fractions: loadPassFractions() }),
    resume: true,
    ...params,
  })
}

// Start the next operation once the run `runId` has finished cleanly (it was just
// told to finish); a run that ended in an error or an E-STOP starts nothing.
export async function startAfter(runId: string, start: () => Promise<void>): Promise<void> {
  const estops = estopsFired()
  for (let i = 0; i < 300; i++) {
    if (estopsFired() !== estops) throw new Error('E-STOP pressed: the next step was not started')
    const op = useOperationStore.getState().operation
    if (op && op.run_id === runId && op.state === 'error') {
      throw new Error('the previous run ended with an error or E-STOP: the next step was not started')
    }
    if (!op || op.run_id !== runId || !isOperationActive(op)) return start()
    await sleep(100)
  }
  throw new Error('the previous run did not finish')
}

async function startWhenConnected(kind: string, params: Record<string, unknown>): Promise<void> {
  const estops = estopsFired()
  let lastError: unknown = null
  for (let i = 0; i < 60; i++) {
    if (estopsFired() !== estops) throw new Error(`E-STOP pressed: ${kind} was not started`)
    try {
      await api.operationStart(kind, params)
      return
    } catch (error) {
      lastError = error
      const message = String((error as Error).message ?? error)
      // Only "not connected yet" is worth waiting out; anything else is final.
      if (!/not connected|503/.test(message)) throw error
      await sleep(500)
    }
  }
  throw lastError
}

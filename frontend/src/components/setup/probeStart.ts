// Starting a measurement right after another maintenance operation: the hand
// is still reconnecting for a moment, so the start is retried until it takes.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useSetupVariant } from '../../state/setupVariant'
import { isV21Family, useTensionFlow } from '../../state/tensionFlow'
import { loadPassFractions, loadPassSlack } from './guidedSettings'

export const SLACK_HINT =
  'Slack test: you hold one joint at a time while its motor winds each way at low current. The free rotation is the slack; more than half a turn fails the joint and blocks calibration.'
export const SWEEP_HINT =
  'Tension sweep: the fingers together per joint kind, then each thumb joint, are driven slowly from one calibrated limit to the other and back while the current is recorded; friction and static load along the travel are compared with the reference curves. Needs a calibrated hand. Keep clear.'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function startSlackTest(params: Record<string, unknown> = {}): Promise<void> {
  const { slackCurrentMa } = useTensionFlow.getState()
  return startWhenConnected('slack_test', { current_ma: slackCurrentMa, ...params })
}

export async function startTensionSweep(params: Record<string, unknown> = {}): Promise<void> {
  const { sweepRepeats, runNote } = useTensionFlow.getState()
  return startWhenConnected('tension_sweep', { repeats: sweepRepeats, ...(runNote ? { note: runNote } : {}), ...params })
}

// Guided tensioning with the page's scoring; the currents come from the hand's
// family defaults unless the Tension step passed its own.
export async function startGuidedTension(params: Record<string, unknown> = {}): Promise<void> {
  const kai = useSetupVariant.getState().variant === 'kai'
  const { offsetDeg } = useTensionFlow.getState()
  return startWhenConnected('guided_tension', {
    tension_offset_deg: offsetDeg,
    ...(kai ? { scoring: 'slack', pass_slack_deg: loadPassSlack() } : { scoring: 'fraction', pass_fractions: loadPassFractions() }),
    resume: true,
    any_hardware: !isV21Family(useAppStore.getState().status?.hardware_version),
    ...params,
  })
}

async function startWhenConnected(kind: string, params: Record<string, unknown>): Promise<void> {
  let lastError: unknown = null
  for (let i = 0; i < 60; i++) {
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

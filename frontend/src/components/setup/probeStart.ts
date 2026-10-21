// Starting a measurement right after another maintenance operation: the hand
// is still reconnecting for a moment, so the start is retried until it takes.

import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useSetupVariant } from '../../state/setupVariant'
import { isV21Family, useTensionFlow } from '../../state/tensionFlow'
import { loadPassFractions, loadPassSlack } from './guidedSettings'

export const PROBE_HINT =
  'Breakaway probe: the current each tendon needs to start moving, the joints of one kind together with the others holding, several passes averaged. Keep clear of the hand.'
export const SLACK_HINT =
  'Slack test: every finger motor winds up to half a turn each way at a current too low to move a tensioned joint. A spool that turns has slack; one that completes the half turn blocks calibration. Keep clear of the hand.'
export const SWEEP_HINT =
  'Tension sweep: the fingers together per joint kind, then each thumb joint, are driven slowly from one calibrated limit to the other and back while the current is recorded; friction and static load along the travel are compared with the reference curves. Needs a calibrated hand. Keep clear.'
export const CHECK_HINT =
  'Tension check: pose the hand mid-range, then the fingers of each joint kind move together 40° and back under one current limit while each motor current is read; the mean is scored against the reference hand. 90–110 % green, 70–90 % yellow (ratchet), under 70 % red, over 110 % grey (left alone). The exact check is the sweep after calibrating. Keep clear of the hand.'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function startTensionProbe(params: Record<string, unknown> = {}): Promise<void> {
  // The operator's start pose and pass count apply wherever the probe is launched from.
  // Breakaway is the measurement; the take-up method only runs when a caller asks for it.
  const { probePose, probeRepeats, runNote } = useTensionFlow.getState()
  return startWhenConnected('tension_probe', {
    pose: probePose, repeats: probeRepeats, methods: ['breakaway'], ...(runNote ? { note: runNote } : {}), ...params,
  })
}

// Between tensioning rounds the calibration is stale, so the probe holds where
// it stands and probes every side the full cap, after a pose prompt.
export async function startTensionCheck(params: Record<string, unknown> = {}): Promise<void> {
  return startTensionProbe({ pose: 'hold', ignore_calibration: true, pose_prompt: true, methods: ['stroke'], ...params })
}

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

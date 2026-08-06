// WebSocket lifecycle: auto-connect, backoff reconnect, message dispatch into
// the stream store, per-topic rate meters (published to zustand at 1 Hz).

import { useAppStore } from '../state/appStore'
import { useEventLogStore } from '../state/eventLogStore'
import { useOperationStore } from '../state/operationStore'
import { useTeleopStore } from '../state/teleopStore'
import {
  latest,
  markDirty,
  pushMeasuredHistory,
} from '../state/streamStore'
import { api } from './rest'
import type {
  ControlState,
  OperationLogPayload,
  OperationSnapshot,
  ServerMessage,
  StatusSnapshot,
  TeleopInstallState,
  TeleopSnapshot,
} from './types'
import { TOPICS } from './types'

// teleop.preview (base64 JPEG frames) is opt-in: the CameraPreview component
// subscribes while visible via subscribeTopic/unsubscribeTopic below.
const DEFAULT_TOPICS = Object.values(TOPICS).filter(
  (topic) => topic !== TOPICS.teleopPreview,
)
const BACKOFF_START_MS = 500
const BACKOFF_MAX_MS = 5000

let socket: WebSocket | null = null
let backoff = BACKOFF_START_MS
let counters: Record<string, number> = {}
let started = false
const extraTopics = new Set<string>()

export function startStreamClient(): void {
  if (started) return
  started = true
  connect()
  setInterval(publishRates, 1000)
}

export function sendCommand(angles: Record<string, number>): boolean {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: 'cmd.joints.target', data: { angles } }),
    )
    return true
  }
  return false
}

// Dynamic (non-default) topic subscriptions. Re-applied on reconnect because
// onopen subscribes DEFAULT_TOPICS ∪ extraTopics.
export function subscribeTopic(topic: string): void {
  extraTopics.add(topic)
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: 'subscribe', data: { topics: [topic] } }),
    )
  }
}

export function unsubscribeTopic(topic: string): void {
  extraTopics.delete(topic)
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: 'unsubscribe', data: { topics: [topic] } }),
    )
  }
}

function connect(): void {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${location.host}/ws`)
  socket = ws

  ws.onopen = () => {
    backoff = BACKOFF_START_MS
    useAppStore.getState().setWsConnected(true)
    ws.send(
      JSON.stringify({
        type: 'subscribe',
        data: { topics: [...DEFAULT_TOPICS, ...extraTopics] },
      }),
    )
    // Hardware may have been swapped while we were away.
    void refreshHandInfo()
    // Hub retention covers reconnects to the SAME backend; after a backend
    // restart there is nothing retained, so a stale 'running' operation or
    // teleop session would wedge every start-gate. REST is authoritative.
    void resyncControlPlanes()
  }

  ws.onmessage = (event) => {
    let message: ServerMessage
    try {
      message = JSON.parse(event.data as string)
    } catch {
      return
    }
    dispatch(message)
  }

  ws.onclose = () => {
    if (socket === ws) socket = null
    useAppStore.getState().setWsConnected(false)
    const delay = backoff + Math.random() * 250
    backoff = Math.min(backoff * 2, BACKOFF_MAX_MS)
    setTimeout(connect, delay)
  }

  ws.onerror = () => ws.close()
}

async function refreshHandInfo(): Promise<void> {
  try {
    useAppStore.getState().setHandInfo(await api.handInfo())
  } catch {
    /* backend not ready yet; the status stream will drive the UI */
  }
}

async function resyncControlPlanes(): Promise<void> {
  try {
    useOperationStore.getState().setOperation((await api.operation()).operation)
  } catch {
    /* keep whatever we have; topic pushes will correct it */
  }
  try {
    useTeleopStore.getState().setSession((await api.teleopState()).session)
  } catch {
    /* teleop may be disabled (--no-teleop) */
  }
}

function dispatch(message: ServerMessage): void {
  const { type, data, t } = message
  counters[type] = (counters[type] ?? 0) + 1

  switch (type) {
    case TOPICS.jointsMeasured: {
      const angles = data.angles as Record<string, number>
      Object.assign(latest.joints.measured, angles)
      latest.joints.tMeasured = t ?? Date.now()
      pushMeasuredHistory(angles, latest.joints.tMeasured)
      markDirty()
      break
    }
    case TOPICS.jointsEstimate:
      Object.assign(latest.joints.estimate, data.angles as object)
      markDirty()
      break
    case TOPICS.jointsTarget:
      Object.assign(latest.joints.target, data.angles as object)
      latest.joints.tTarget = t ?? Date.now()
      markDirty()
      break
    case TOPICS.jointsCorrection:
      Object.assign(latest.joints.trim, data.trim as object)
      markDirty()
      break
    case TOPICS.tactileForces:
      latest.tactile.forces = data.forces as typeof latest.tactile.forces
      latest.tactile.tForces = t ?? Date.now()
      markDirty()
      break
    case TOPICS.tactileTaxels:
      latest.tactile.taxels = data.taxels as typeof latest.tactile.taxels
      latest.tactile.tTaxels = t ?? Date.now()
      markDirty()
      break
    case TOPICS.motorsTelemetry:
      latest.motors.temps = data.temps as Record<string, number>
      latest.motors.currents = data.currents as Record<string, number>
      markDirty()
      break
    case TOPICS.stats:
      latest.stats = data
      markDirty()
      break
    case TOPICS.status: {
      const status = data as unknown as StatusSnapshot
      const previous = useAppStore.getState().status
      if (previous?.state !== status.state) {
        useEventLogStore
          .getState()
          .pushEvent(
            'status',
            `state → ${status.state}${status.message ? ` (${status.message})` : ''}`,
          )
      }
      useAppStore.getState().setStatus(status)
      // A fresh session may change capabilities/joints.
      if (status.state === 'connected' || status.state === 'degraded') {
        void refreshHandInfo()
      }
      break
    }
    case TOPICS.controlState:
      useAppStore.getState().setControl(data as unknown as ControlState)
      break
    case TOPICS.operationState:
      useOperationStore
        .getState()
        .setOperation(data as unknown as OperationSnapshot)
      break
    case TOPICS.operationLog:
      useOperationStore
        .getState()
        .mergeLog(data as unknown as OperationLogPayload)
      break
    case TOPICS.teleopState: {
      const session = data as unknown as TeleopSnapshot
      useTeleopStore.getState().setSession(session)
      if (session.state === 'idle' || session.state === 'error') {
        // Stale ghost poses must not survive the session.
        for (const key of Object.keys(latest.joints.teleopTarget)) {
          delete latest.joints.teleopTarget[key]
        }
        latest.teleop.preview = null
        markDirty()
      }
      break
    }
    case TOPICS.teleopTargets:
      Object.assign(latest.joints.teleopTarget, data.angles as object)
      latest.joints.tTeleopTarget = t ?? Date.now()
      markDirty()
      break
    case TOPICS.teleopLog:
      useTeleopStore
        .getState()
        .mergeLog(data as unknown as OperationLogPayload)
      break
    case TOPICS.teleopInstall: {
      const install = data as unknown as TeleopInstallState
      useTeleopStore.getState().setInstall(install)
      // A finished install changes runner availability; re-probe so the card
      // collapses back to the source picker without a reload.
      if (install.finished) {
        void api
          .teleopSources()
          .then(useTeleopStore.getState().setSources)
          .catch(() => undefined)
      }
      break
    }
    case TOPICS.teleopInstallLog:
      useTeleopStore
        .getState()
        .mergeInstallLog(data as unknown as OperationLogPayload)
      break
    case TOPICS.teleopPreview:
      latest.teleop.preview = data as { jpeg: string; seq: number | null }
      markDirty()
      break
    case TOPICS.error: {
      const message = (data.message as string) ?? 'unknown error'
      useAppStore.getState().setError(message)
      useEventLogStore.getState().pushEvent('error', message)
      break
    }
  }
}

function publishRates(): void {
  useAppStore.getState().setRates(counters)
  counters = {}
}

// WebSocket lifecycle: auto-connect, backoff reconnect, message dispatch into
// the stream store, per-topic rate meters (published to zustand at 1 Hz).

import { refreshHandInfo } from '../components/hand/handStore'
import { useAppStore } from '../state/appStore'
import { useEventLogStore } from '../state/eventLogStore'
import { useOperationStore } from '../state/operationStore'
import { useAppSessionStore } from '../state/appSessionStore'
import {
  latest,
  markDirty,
  pushMeasuredHistory,
} from '../state/streamStore'
import { api } from './rest'
import type {
  AppFrames,
  AppSnapshot,
  ControlState,
  MotorsFaults,
  OperationLogPayload,
  OperationSnapshot,
  SensorsHealth,
  ServerMessage,
  StatusSnapshot,
} from './types'
import { TOPICS } from './types'

// app.frames (base64 JPEG pictures) is opt-in: picture tiles subscribe while
// visible via subscribeTopic/unsubscribeTopic below.
const DEFAULT_TOPICS = Object.values(TOPICS).filter(
  (topic) => topic !== TOPICS.appFrames,
)
const BACKOFF_START_MS = 500
const BACKOFF_MAX_MS = 5000

let socket: WebSocket | null = null
let backoff = BACKOFF_START_MS
let counters: Record<string, number> = {}
let started = false
// The banner text of the last error that ended a connection, cleared on reconnect.
let connectionError: string | null = null
// Opt-in topics, counted: several components may want the same one.
const extraTopics = new Map<string, number>()

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
  const count = extraTopics.get(topic) ?? 0
  extraTopics.set(topic, count + 1)
  if (count === 0 && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: 'subscribe', data: { topics: [topic] } }),
    )
  }
}

export function unsubscribeTopic(topic: string): void {
  const count = (extraTopics.get(topic) ?? 0) - 1
  if (count > 0) {
    extraTopics.set(topic, count)
    return
  }
  extraTopics.delete(topic)
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(
      JSON.stringify({ type: 'unsubscribe', data: { topics: [topic] } }),
    )
  }
}

function connect(): void {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  // client=browser: the app session disengages when the last tab is gone.
  const ws = new WebSocket(`${protocol}//${location.host}/ws?client=browser`)
  socket = ws

  ws.onopen = () => {
    backoff = BACKOFF_START_MS
    useAppStore.getState().setWsConnected(true)
    ws.send(
      JSON.stringify({
        type: 'subscribe',
        data: { topics: [...DEFAULT_TOPICS, ...extraTopics.keys()] },
      }),
    )
    // Hardware may have been swapped while we were away.
    void refreshHandInfo()
    // Hub retention covers reconnects to the SAME backend; after a backend
    // restart there is nothing retained, so a stale 'running' operation or
    // app session would wedge every start-gate. REST is authoritative.
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

async function resyncControlPlanes(): Promise<void> {
  try {
    useOperationStore.getState().setOperation((await api.operation()).operation)
  } catch {
    /* keep whatever we have; topic pushes will correct it */
  }
  try {
    useAppSessionStore.getState().setSession((await api.appState()).session)
  } catch {
    /* app sessions may be disabled (--no-apps) */
  }
  void useAppSessionStore.getState().refreshApps()
}

// Event-log entries for measured-stream fallback transitions: which joint
// sensor went bad (and why), and when its measured tracking came back.
let lastSuppressed: Record<string, string> = {}
function logSuppressionChanges(health: SensorsHealth): void {
  const suppressed = health.encoders?.suppressed ?? {}
  const push = useEventLogStore.getState().pushEvent
  for (const [joint, reason] of Object.entries(suppressed)) {
    if (!(joint in lastSuppressed)) {
      push(
        'error',
        `${joint} joint sensor unhealthy (${reason}) — measured stream ` +
          'dropped; 3D model and joint displays fall back to the motor ' +
          'estimate',
      )
    }
  }
  for (const joint of Object.keys(lastSuppressed)) {
    if (!(joint in suppressed)) {
      push(
        'status',
        `${joint} joint sensor reads clean again — measured tracking restored`,
      )
    }
  }
  lastSuppressed = suppressed
}

// Event-log entries for adherence transitions: which motor stopped following
// its commanded target, and when it recovered.
let lastStalled: Record<string, boolean> = {}
function logFaultChanges(faults: MotorsFaults): void {
  const push = useEventLogStore.getState().pushEvent
  const next: Record<string, boolean> = {}
  for (const [id, motor] of Object.entries(faults.motors)) {
    const stalled = motor.tracking !== null && !motor.tracking.following
    next[id] = stalled
    const label = `motor ${id}${motor.joint ? ` (${motor.joint})` : ''}`
    if (stalled && !lastStalled[id]) {
      push(
        'error',
        `${label} is not following its command — off by ` +
          `${motor.tracking!.deviation_deg?.toFixed(1) ?? '?'}°`,
      )
    } else if (!stalled && lastStalled[id]) {
      push('status', `${label} is following its command again`)
    }
  }
  lastStalled = next
}

function dispatch(message: ServerMessage): void {
  const { type, data, t } = message
  counters[type] = (counters[type] ?? 0) + 1

  switch (type) {
    case TOPICS.jointsMeasured: {
      const angles = data.angles as Record<string, number>
      Object.assign(latest.joints.measured, angles)
      // Joints with a distrusted encoder are dropped server-side; delete
      // any stale value we still hold so the estimate fallback actually
      // takes over instead of a frozen last-noisy reading.
      for (const joint of (data.suppressed as string[] | undefined) ?? []) {
        delete latest.joints.measured[joint]
      }
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
      latest.motors.positions =
        (data.positions as Record<string, number> | undefined) ??
        latest.motors.positions
      latest.motors.maxTempC =
        (data.max_temp_c as number | undefined) ?? latest.motors.maxTempC
      latest.motors.shutdownTemps =
        (data.shutdown_temps as Record<string, number> | undefined) ??
        latest.motors.shutdownTemps
      markDirty()
      break
    case TOPICS.motorsFaults: {
      const faults = data as unknown as MotorsFaults
      logFaultChanges(faults)
      latest.motors.faults = faults
      markDirty()
      break
    }
    case TOPICS.stats:
      latest.stats = data
      markDirty()
      break
    case TOPICS.sensorsHealth: {
      const health = data as unknown as SensorsHealth
      logSuppressionChanges(health)
      latest.health = health
      markDirty()
      break
    }
    case TOPICS.status: {
      const status = data as unknown as StatusSnapshot
      const { status: previous, handInfo } = useAppStore.getState()
      if (previous?.state !== status.state) {
        useEventLogStore
          .getState()
          .pushEvent(
            'status',
            `state → ${status.state}${status.message ? ` (${status.message})` : ''}`,
          )
      }
      // The backend re-derives the model from the hardware, so this changes
      // when a hand that was off comes up, or when a different one is plugged
      // in. Everything model-shaped (joints, ROMs, 3D side) has to follow.
      const modelChanged = !!status.model && status.model !== previous?.model
      if (modelChanged && previous?.model) {
        useEventLogStore
          .getState()
          .pushEvent('status', `hand → ${status.model}`)
      }
      useAppStore.getState().setStatus(status)
      // A connection-loss message is stale once a session is up again; any later error stays.
      if (connectionError && (status.state === 'connected' || status.state === 'degraded')) {
        if (useAppStore.getState().error === connectionError) useAppStore.getState().setError(null)
        connectionError = null
      }
      // A fresh session may change capabilities/joints.
      if (
        status.state === 'connected' ||
        status.state === 'degraded' ||
        modelChanged ||
        (!!status.model && status.model !== handInfo?.model_name)
      ) {
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
    case TOPICS.appState: {
      const session = data as unknown as AppSnapshot
      const previous = useAppSessionStore.getState().session
      useAppSessionStore.getState().setSession(session)
      if (
        session.state !== 'preview' &&
        session.state !== 'engaged' &&
        session.state !== 'starting'
      ) {
        clearAppFrames()
      } else if (previous && previous.session_id !== session.session_id) {
        clearAppFrames()
      }
      break
    }
    case TOPICS.appTargets: {
      const sessionId = useAppSessionStore.getState().session?.session_id
      if (data.session_id !== sessionId) {
        // A cleared ghost, or one from an earlier session.
        clearGhost()
        break
      }
      Object.assign(latest.joints.appTarget, data.angles as object)
      latest.joints.tAppTarget = t ?? Date.now()
      markDirty()
      break
    }
    case TOPICS.appLog:
      useAppSessionStore
        .getState()
        .mergeLog(data as unknown as OperationLogPayload)
      break
    case TOPICS.appFrames: {
      const frames = data as unknown as AppFrames
      const sessionId = useAppSessionStore.getState().session?.session_id
      latest.app.frames = frames.session_id === sessionId ? frames.streams : {}
      markDirty()
      break
    }
    case TOPICS.error: {
      const message = (data.message as string) ?? 'unknown error'
      connectionError = data.connection ? message : null
      useAppStore.getState().setError(message)
      useEventLogStore.getState().pushEvent('error', message)
      break
    }
  }
}

function clearGhost(): void {
  for (const key of Object.keys(latest.joints.appTarget)) {
    delete latest.joints.appTarget[key]
  }
  markDirty()
}

// Stale ghost poses and pictures must not survive their session.
function clearAppFrames(): void {
  clearGhost()
  latest.app.frames = {}
}

function publishRates(): void {
  useAppStore.getState().setRates(counters)
  counters = {}
}

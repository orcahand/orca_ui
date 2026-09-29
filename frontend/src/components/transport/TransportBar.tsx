// Global operation strip, rendered under the header on every tab while an
// operation is active (or its terminal snapshot is still on display).
// Kind-aware renderers; awaiting_input prompts become inline buttons so any
// tab can answer them. Designed as a generic control-session strip — a
// future teleop session adds a renderer here, not a redesign.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { OperationSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { operationLabel, useOperationStore } from '../../state/operationStore'
import { TeleopBar } from './TeleopBar'

const DONE_LINGER_MS = 3000

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const sendInput = (value: string) => void api.operationInput(value).catch(fail)

// replay/demo detail is "name · 12.4s @ ×1" — the only place total duration
// travels. Loop cycles rewrite it to "name · cycle N", so the caller caches
// the last successful parse per run.
function parseTotalSeconds(detail: string | null): number | null {
  const match = detail?.match(/(\d+(?:\.\d+)?)s\s*@/)
  return match ? parseFloat(match[1]) : null
}

function fmtSeconds(seconds: number): string {
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60)
    return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
  }
  return `${seconds.toFixed(1)}s`
}

export function TransportBar() {
  // Two independent control-session strips stack: an operation bar and a
  // teleop bar. The arbiter guarantees at most one of them OWNS the hand,
  // but a teleop preview under a running operation is legitimate.
  return (
    <>
      <OperationBar />
      <TeleopBar />
    </>
  )
}

function OperationBar() {
  const operation = useOperationStore((s) => s.operation)
  const [dismissedRun, setDismissedRun] = useState<string | null>(null)
  const [expiredRun, setExpiredRun] = useState<string | null>(null)

  const runId = operation?.run_id ?? null
  const state = operation?.state ?? null

  // Terminal done: linger briefly, then disappear.
  useEffect(() => {
    if (!runId || state !== 'done') return
    const timer = window.setTimeout(() => setExpiredRun(runId), DONE_LINGER_MS)
    return () => window.clearTimeout(timer)
  }, [runId, state])

  if (!operation) return null
  if (operation.state === 'done' && expiredRun === operation.run_id) return null
  if (operation.state === 'error' && dismissedRun === operation.run_id) {
    return null
  }

  if (operation.state === 'error') {
    const dismiss = () => {
      // Belt-and-braces with the global banner: if it shows this same
      // failure, dismissing the bar clears it too.
      const banner = `${operationLabel(operation.kind)} failed: ${operation.error ?? 'unknown error'}`
      const app = useAppStore.getState()
      if (app.error === banner) app.setError(null)
      setDismissedRun(operation.run_id)
    }
    return (
      <div className="transport-bar error">
        <span className="transport-kind">{operationLabel(operation.kind)}</span>
        <span className="transport-detail">
          {operation.error ?? operation.detail ?? 'failed'}
        </span>
        <div className="transport-controls">
          <button
            className="btn btn-secondary"
            title="dismiss"
            onClick={dismiss}
          >
            ✕
          </button>
        </div>
      </div>
    )
  }

  if (operation.state === 'done') {
    return (
      <div className="transport-bar done">
        <span className="transport-kind">✓ {operationLabel(operation.kind)}</span>
        <span className="transport-detail">{operation.detail ?? 'done'}</span>
      </div>
    )
  }

  if (operation.kind === 'replay' || operation.kind === 'demo') {
    return <PlaybackBar operation={operation} />
  }
  if (operation.kind === 'record') {
    return <RecordBar operation={operation} />
  }
  return <MaintenanceBar operation={operation} />
}

// ----- replay / demo ---------------------------------------------------------

function PlaybackBar({ operation }: { operation: OperationSnapshot }) {
  const totalRef = useRef<{ run: string; total: number } | null>(null)
  const parsed = parseTotalSeconds(operation.detail)
  if (parsed !== null) {
    totalRef.current = { run: operation.run_id, total: parsed }
  } else if (totalRef.current?.run !== operation.run_id) {
    totalRef.current = null
  }
  const total = totalRef.current?.total ?? null

  const name = String(operation.params.name ?? operation.kind)
  const speed = Number(operation.params.speed ?? 1)
  const loop = Boolean(operation.params.loop)
  const progress = operation.progress
  const paused = operation.state === 'paused'
  const stopping = operation.state === 'stopping'

  return (
    <div className="transport-bar">
      <span className="transport-kind">▶ {name}</span>
      <span className="transport-detail">
        ×{speed}
        {loop ? ' · loop' : ''}
        {operation.kind === 'demo' ? ' · demo' : ''}
      </span>
      {paused && <span className="transport-paused">paused</span>}
      <ProgressTrack progress={progress} />
      <span className="transport-time">
        {total !== null && progress !== null
          ? `${fmtSeconds(progress * total)} / ${fmtSeconds(total)}`
          : operation.detail}
      </span>
      <div className="transport-controls">
        {paused ? (
          <button
            className="btn btn-primary"
            title="resume playback"
            onClick={() => void api.operationResume().catch(fail)}
          >
            ▶
          </button>
        ) : (
          <button
            className="btn btn-secondary"
            disabled={stopping}
            title="pause playback"
            onClick={() => void api.operationPause().catch(fail)}
          >
            ⏸
          </button>
        )}
        <StopButton stopping={stopping} />
      </div>
    </div>
  )
}

// ----- record ----------------------------------------------------------------

function RecordBar({ operation }: { operation: OperationSnapshot }) {
  const mode = String(operation.params.mode ?? 'continuous')
  const frequency = operation.params.frequency
  const waypoints = mode === 'waypoints'
  const awaiting =
    operation.state === 'awaiting_input' ? operation.awaiting : null

  return (
    <div className="transport-bar">
      <span className="transport-kind rec">
        <span className="rec-dot" /> REC
      </span>
      <span className="transport-detail">
        {mode}
        {!waypoints && frequency != null ? ` @ ${frequency}Hz` : ''}
        {awaiting
          ? ` · ${awaiting.prompt}`
          : operation.detail
            ? ` · ${operation.detail}`
            : ''}
      </span>
      <div className="transport-controls">
        {waypoints && awaiting ? (
          // Waypoint mode parks in awaiting_input; its options ARE the
          // record controls (Capture / Stop & save).
          awaiting.options.map((option) => (
            <button
              key={option}
              className="btn btn-primary"
              onClick={() => sendInput(option)}
            >
              {option.toLowerCase()}
            </button>
          ))
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => sendInput('save')}
          >
            ■ stop &amp; save
          </button>
        )}
        {/* No plain stop: /api/operation/stop ABORTS a recording without
            saving — ending a record is an input, never a stop. */}
      </div>
    </div>
  )
}

// ----- calibrate / tension / wizard (and unknown kinds) -----------------------

function MaintenanceBar({ operation }: { operation: OperationSnapshot }) {
  const stopping = operation.state === 'stopping'
  const awaiting =
    operation.state === 'awaiting_input' ? operation.awaiting : null
  return (
    <div className="transport-bar">
      <span className="transport-kind">{operationLabel(operation.kind)}</span>
      {operation.phase && (
        <span className="transport-phase">{operation.phase}</span>
      )}
      {operation.detail && (
        <span className="transport-detail">{operation.detail}</span>
      )}
      <ProgressTrack progress={operation.progress} />
      {awaiting && (
        <span className="transport-awaiting">
          <span>{awaiting.prompt}</span>
          {awaiting.options.map((option) => (
            <button
              key={option}
              className="btn btn-primary"
              onClick={() => sendInput(option)}
            >
              {option}
            </button>
          ))}
        </span>
      )}
      <div className="transport-controls">
        <StopButton stopping={stopping} />
      </div>
    </div>
  )
}

// ----- shared bits -------------------------------------------------------------

function ProgressTrack({ progress }: { progress: number | null }) {
  if (progress === null) return null
  const pct = Math.min(Math.max(progress, 0), 1) * 100
  return (
    <div className="transport-progress">
      <div className="transport-progress-fill" style={{ width: `${pct}%` }} />
    </div>
  )
}

function StopButton({ stopping }: { stopping: boolean }) {
  return (
    <button
      className="btn btn-danger"
      disabled={stopping}
      title="stop the operation"
      onClick={() => void api.operationStop().catch(fail)}
    >
      ■ stop
    </button>
  )
}

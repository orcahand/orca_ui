// Speed cap for lone joint jumps, next to the current ceiling on the
// dashboard. A typed angle or a slider grabbed far from the pose is ramped at
// no more than this, so a single command cannot whip a tendon. Streams —
// replay, teleop, a slider drag — pace themselves and are not capped, which is
// what lets playback speed scale time instead of range.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

// Mirrors the backend's bounds (commands.MIN/MAX_MAX_TARGET_SPEED_DEG_S).
const MIN_DEG_S = 10
const MAX_DEG_S = 2000
const STEP_DEG_S = 10

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function MaxSpeedControl() {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const [pending, setPending] = useState<number | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const sent = useRef<number | null>(null)

  const live = control?.max_target_speed_deg_s ?? null
  const defaultValue = control?.default_max_target_speed_deg_s ?? null

  useEffect(() => {
    if (pending !== null && live === pending) {
      setPending(null)
      sent.current = null
    }
  }, [live, pending])

  if (live === null) return null
  const value = pending ?? live

  const commit = (degS: number) => {
    const target = clamp(Math.round(degS), MIN_DEG_S, MAX_DEG_S)
    setText(null)
    if (target === live) {
      setPending(null)
      sent.current = null
      return
    }
    if (target === sent.current) return
    sent.current = target
    setPending(target)
    setBusy(true)
    api
      .setMaxTargetSpeed(target)
      .then(() => setError(null))
      .catch((error: unknown) => {
        sent.current = null
        setPending(null)
        setError(String((error as Error).message ?? error))
      })
      .finally(() => setBusy(false))
  }

  const commitFrom = (target: EventTarget) =>
    commit(parseInt((target as HTMLInputElement).value, 10))

  return (
    <div className="current-row">
      <span className="current-label">max jump speed</span>
      <input
        className="current-slider"
        type="range"
        min={MIN_DEG_S}
        max={MAX_DEG_S}
        step={STEP_DEG_S}
        value={clamp(value, MIN_DEG_S, MAX_DEG_S)}
        title="how fast a single commanded jump may move a joint (deg/s)"
        onChange={(e) => setPending(parseInt(e.target.value, 10))}
        onPointerUp={(e) => commitFrom(e.target)}
        onLostPointerCapture={(e) => commitFrom(e.target)}
        onKeyUp={(e) => commitFrom(e.target)}
        onBlur={(e) => commitFrom(e.target)}
      />
      <input
        className="current-input"
        type="number"
        min={MIN_DEG_S}
        max={MAX_DEG_S}
        step={STEP_DEG_S}
        value={text ?? String(value)}
        title="type a cap in deg/s and press Enter"
        onFocus={(e) => {
          setText(String(value))
          e.target.select()
        }}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commitFrom(e.target)
          if (e.key === 'Escape') setText(null)
        }}
        onBlur={(e) => {
          if (text !== null) commitFrom(e.target)
        }}
      />
      <span className="current-unit">°/s</span>
      {defaultValue !== null && (
        <button
          className="btn btn-secondary current-default"
          disabled={busy || value === defaultValue}
          title={`restore the default cap (${defaultValue} °/s)`}
          onClick={() => commit(defaultValue)}
        >
          default {defaultValue}
        </button>
      )}
      <span className="current-note">
        caps a single jump (typed angle, slider grab); replay and teleop set
        their own pace and are not limited by it
      </span>
    </div>
  )
}

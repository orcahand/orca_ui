// Motor current ceiling, in situ on the dashboard. It is the force/safety
// envelope — the one knob you reach for when a grasp is too weak or a tendon
// is taking too much — so it lives next to the sliders rather than only in
// the Motors tab's tuning form, where it sat behind a shared Apply button.
//
// Deliberately NOT gated on the control-source owner: the backend allows it
// at any time, and lowering the ceiling while an operation drives the hand is
// exactly when you want it reachable.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

// The request schema accepts 1..2000 mA, but orca_core refuses a ceiling
// below the hand's calibration current — control.max_current_floor carries
// that limit, and everything here clamps to it so a drag can never produce
// the 400.
const MAX_MA = 2000
const STEP_MA = 10

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function MaxCurrentControl() {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  // Value the user is dragging or has just sent, held until the backend's
  // control.state echo catches up — otherwise the slider snaps back for a
  // frame on every commit.
  const [pending, setPending] = useState<number | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Last value actually written. A drag ends through whichever of pointerup /
  // keyup / blur lands first — they all commit, and this keeps the extras
  // from becoming duplicate writes.
  const sent = useRef<number | null>(null)

  const live = control?.max_current ?? null
  const configDefault = control?.config_max_current ?? null
  const floor = control?.max_current_floor ?? 1

  useEffect(() => {
    if (pending !== null && live === pending) {
      setPending(null)
      sent.current = null
    }
  }, [live, pending])

  if (live === null) return null
  const value = pending ?? live

  const commit = (ma: number) => {
    const target = clamp(Math.round(ma), floor, MAX_MA)
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
      .setMaxCurrent(target)
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
      <span className="current-label">max current</span>
      <input
        className="current-slider"
        type="range"
        min={floor}
        max={MAX_MA}
        step={STEP_MA}
        value={clamp(value, floor, MAX_MA)}
        title={
          `motor current ceiling — lower is gentler and cooler ` +
          `(floor ${floor} mA, the hand's calibration current)`
        }
        // Drag freely; the write goes out once, when the drag ends.
        onChange={(e) => setPending(parseInt(e.target.value, 10))}
        onPointerUp={(e) => commitFrom(e.target)}
        onLostPointerCapture={(e) => commitFrom(e.target)}
        onKeyUp={(e) => commitFrom(e.target)}
        onBlur={(e) => commitFrom(e.target)}
      />
      <input
        className="current-input"
        type="number"
        min={floor}
        max={MAX_MA}
        step={STEP_MA}
        value={text ?? String(value)}
        title="type a ceiling in mA and press Enter"
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
      <span className="current-unit">mA</span>
      {configDefault !== null && (
        <button
          className="btn btn-secondary current-default"
          disabled={busy || value === configDefault}
          title={`restore config.yaml's ceiling (${configDefault} mA)`}
          onClick={() => commit(configDefault)}
        >
          default {configDefault}
        </button>
      )}
      <span className="current-note">
        lower is gentler on tendons; applies to every motor at once (floor{' '}
        {floor} mA — the hand's calibration current)
      </span>
    </div>
  )
}

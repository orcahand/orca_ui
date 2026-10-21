// Live per-motor readouts at display rate, without React re-rendering on
// every 10 Hz sample: components register a callback that mutates DOM refs.
// Also keeps the short history the bench chart draws from.

import { useEffect, useRef } from 'react'
import type { LatestFrames } from '../state/streamStore'
import { subscribeFrames } from '../state/streamStore'
import { RingBuffer } from '../state/ringBuffer'

export const HISTORY_S = 30
const HISTORY_CAPACITY = 1024

export const benchHistory = {
  time: new RingBuffer(HISTORY_CAPACITY, Float64Array), // epoch seconds
  positions: new Map<string, RingBuffer>(),
  currents: new Map<string, RingBuffer>(),
}

function ring(map: Map<string, RingBuffer>, id: string): RingBuffer {
  let buffer = map.get(id)
  if (!buffer) {
    buffer = new RingBuffer(HISTORY_CAPACITY)
    map.set(id, buffer)
  }
  return buffer
}

let lastRecorded = 0
let recorderInstalled = false

// One recorder for the page, installed on first use: every new motors.state
// sample lands in the rings exactly once, however many components listen.
function installRecorder(): void {
  if (recorderInstalled) return
  recorderInstalled = true
  subscribeFrames((frames) => {
    const t = frames.motors.tState
    if (!t || t === lastRecorded) return
    lastRecorded = t
    benchHistory.time.push(t / 1000)
    const ids = new Set([
      ...benchHistory.positions.keys(),
      ...Object.keys(frames.motors.positions),
    ])
    for (const id of ids) {
      ring(benchHistory.positions, id).push(frames.motors.positions[id] ?? NaN)
      ring(benchHistory.currents, id).push(frames.motors.currents[id] ?? NaN)
    }
  })
}

export function useMotorLive(callback: (frames: LatestFrames) => void): void {
  const ref = useRef(callback)
  ref.current = callback
  useEffect(() => {
    installRecorder()
    return subscribeFrames((frames) => ref.current(frames))
  }, [])
}

export function formatDeg(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined || Number.isNaN(value)
    ? '—'
    : `${value.toFixed(digits)}°`
}

export function formatMa(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value)
    ? '—'
    : `${Math.round(value)} mA`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m ${String(r).padStart(2, '0')}s`
  return `${r}s`
}

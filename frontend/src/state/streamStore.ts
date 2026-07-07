// The data plane: mutable latest-value slots + history rings, written by the
// WS handler, fanned out to imperative subscribers on requestAnimationFrame.
// High-rate data never passes through React state.

import type { Finger, Vec3 } from '../api/types'
import { RingBuffer } from './ringBuffer'

export interface LatestFrames {
  joints: {
    measured: Record<string, number>
    estimate: Record<string, number>
    target: Record<string, number>
    trim: Record<string, number>
    tMeasured: number // ms epoch of last measured update
    tTarget: number
  }
  tactile: {
    forces: Partial<Record<Finger, Vec3>> | null
    taxels: Partial<Record<Finger, Vec3[]>> | null
    tForces: number
    tTaxels: number
  }
  motors: {
    temps: Record<string, number>
    currents: Record<string, number>
  }
  stats: Record<string, unknown> | null
}

export const latest: LatestFrames = {
  joints: {
    measured: {},
    estimate: {},
    target: {},
    trim: {},
    tMeasured: 0,
    tTarget: 0,
  },
  tactile: { forces: null, taxels: null, tForces: 0, tTaxels: 0 },
  motors: { temps: {}, currents: {} },
  stats: null,
}

// ----- sparkline history (measured + target per joint, shared time ring) ----

const HISTORY_CAPACITY = 1024

export const jointHistory = {
  time: new RingBuffer(HISTORY_CAPACITY),
  measured: new Map<string, RingBuffer>(),
  target: new Map<string, RingBuffer>(),
}

function ring(map: Map<string, RingBuffer>, joint: string): RingBuffer {
  let buffer = map.get(joint)
  if (!buffer) {
    buffer = new RingBuffer(HISTORY_CAPACITY)
    map.set(joint, buffer)
  }
  return buffer
}

export function pushMeasuredHistory(
  angles: Record<string, number>,
  tMs: number,
): void {
  jointHistory.time.push(tMs / 1000)
  for (const [joint, angle] of Object.entries(angles)) {
    ring(jointHistory.measured, joint).push(angle)
    // Target sampled on the same time base so uPlot series stay aligned.
    ring(jointHistory.target, joint).push(
      latest.joints.target[joint] ?? NaN,
    )
  }
}

// ----- rAF fan-out -----------------------------------------------------------

type FrameCallback = (frames: LatestFrames) => void

const subscribers = new Set<FrameCallback>()
let dirty = false
let rafRunning = false

export function markDirty(): void {
  dirty = true
  if (!rafRunning) {
    rafRunning = true
    requestAnimationFrame(loop)
  }
}

function loop(): void {
  if (dirty) {
    dirty = false
    for (const callback of subscribers) {
      try {
        callback(latest)
      } catch (error) {
        console.error('frame subscriber failed', error)
      }
    }
  }
  if (subscribers.size > 0) {
    requestAnimationFrame(loop)
  } else {
    rafRunning = false
  }
}

export function subscribeFrames(callback: FrameCallback): () => void {
  subscribers.add(callback)
  if (!rafRunning) {
    rafRunning = true
    requestAnimationFrame(loop)
  }
  return () => subscribers.delete(callback)
}

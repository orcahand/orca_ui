// Register an imperative per-display-frame callback over the latest stream
// data. The callback mutates DOM/three objects via refs — no React re-render.

import { useEffect, useRef } from 'react'
import type { LatestFrames } from '../state/streamStore'
import { subscribeFrames } from '../state/streamStore'

export function useStreamFrame(callback: (frames: LatestFrames) => void): void {
  const ref = useRef(callback)
  ref.current = callback
  useEffect(() => subscribeFrames((frames) => ref.current(frames)), [])
}

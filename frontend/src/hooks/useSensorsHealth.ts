// React-state view of the 1 Hz sensors.health topic. The payload flows
// through the rAF stream store like all telemetry; a JSON compare keeps
// re-renders at topic rate, so panels can fuse health verdicts into their
// normal render path.

import { useRef, useState } from 'react'
import type { SensorsHealth } from '../api/types'
import { useStreamFrame } from './useStreamFrame'

export function useSensorsHealth(): SensorsHealth | null {
  const [health, setHealth] = useState<SensorsHealth | null>(null)
  const lastJson = useRef('')
  useStreamFrame((frames) => {
    const json = JSON.stringify(frames.health)
    if (json !== lastJson.current) {
      lastJson.current = json
      setHealth(frames.health)
    }
  })
  return health
}

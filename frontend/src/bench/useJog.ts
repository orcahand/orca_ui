// Jogging one motor by a step, with press-and-hold repeat. Shared by the
// cycle mode's motor cards and the fingers mode's joint rows, so a jog is
// the same jog everywhere: arm direct motor mode on first use, one accepted
// write per step, optimistic from the last write while the button is held.

import { useRef, useState, type MutableRefObject } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'

// Below the backend's 0.8 rad per-move cap, so every jog is one accepted write.
export const JOG_STEPS_DEG = [2, 10, 30]
const JOG_REPEAT_MS = 180
const JOG_REPEAT_AFTER_MS = 400
const DEG = Math.PI / 180

export function useJog(
  motorId: number,
  livePos: MutableRefObject<number | null>,
  stepDeg: number,
  enabled: boolean,
): {
  jogging: boolean
  startRepeat(direction: 1 | -1): void
  stopRepeat(): void
} {
  const setError = useAppStore((s) => s.setError)
  const [jogging, setJogging] = useState(false)
  const repeat = useRef<{ timer: number | null; interval: number | null }>({
    timer: null,
    interval: null,
  })

  const stopRepeat = () => {
    const r = repeat.current
    if (r.timer !== null) window.clearTimeout(r.timer)
    if (r.interval !== null) window.clearInterval(r.interval)
    r.timer = null
    r.interval = null
    setJogging(false)
  }

  const jogOnce = async (direction: 1 | -1) => {
    try {
      let positionDeg = livePos.current
      if (positionDeg === null) {
        const snapshot = await api.motorsDirect()
        const entry = snapshot.motors.find((m) => m.id === motorId)
        if (!entry) return
        positionDeg = entry.position / DEG
      }
      if (!useAppStore.getState().control?.direct_motor_mode) {
        await api.motorsDirectMode(true)
      }
      const target = (positionDeg + direction * stepDeg) * DEG
      await api.motorsDirectPosition(motorId, target)
      // Optimistic: the next stream sample confirms, and a held button keeps
      // stepping from where the last write asked for.
      livePos.current = positionDeg + direction * stepDeg
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
      stopRepeat()
    }
  }

  const startRepeat = (direction: 1 | -1) => {
    if (!enabled) return
    setJogging(true)
    void jogOnce(direction)
    repeat.current.timer = window.setTimeout(() => {
      repeat.current.interval = window.setInterval(() => void jogOnce(direction), JOG_REPEAT_MS)
    }, JOG_REPEAT_AFTER_MS)
  }

  return { jogging, startRepeat, stopRepeat }
}

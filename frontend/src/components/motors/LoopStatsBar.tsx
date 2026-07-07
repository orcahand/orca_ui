// 1 Hz loop diagnostics: cycles / overruns / e-stops / dt / fallback badge.

import { useState } from 'react'
import { useStreamFrame } from '../../hooks/useStreamFrame'

interface LoopStats {
  cycles_ok?: number
  cycles_overrun?: number
  e_stops?: number
  last_dt_s?: number
  fallback_active?: boolean
}

export function LoopStatsBar() {
  const [stats, setStats] = useState<LoopStats | null>(null)
  const [lastJson, setLastJson] = useState('')

  useStreamFrame((frames) => {
    const loop = (frames.stats as { loop?: LoopStats } | null)?.loop
    if (!loop) return
    const json = JSON.stringify(loop)
    if (json !== lastJson) {
      setLastJson(json)
      setStats(loop)
    }
  })

  if (!stats) return null
  return (
    <div
      style={{
        marginTop: 8,
        fontSize: 9,
        color: 'var(--dimmer)',
        display: 'flex',
        gap: 12,
        alignItems: 'center',
      }}
    >
      <span>cycles {stats.cycles_ok ?? 0}</span>
      <span>overrun {stats.cycles_overrun ?? 0}</span>
      <span>e-stops {stats.e_stops ?? 0}</span>
      <span>dt {((stats.last_dt_s ?? 0) * 1000).toFixed(1)}ms</span>
      {stats.fallback_active && (
        <span className="capability-badge warn">LOOP FALLBACK</span>
      )}
    </div>
  )
}

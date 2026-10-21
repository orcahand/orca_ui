// The operation log's tail: the run's plan, its progress lines, its report.

import { useOperationStore } from '../state/operationStore'

const LINES = 8

export function BenchLog() {
  const lines = useOperationStore((s) => s.logLines)
  if (lines.length === 0) return null
  const tail = lines.slice(-LINES)
  return (
    <section className="panel bench-log">
      {tail.map((entry) => (
        <div key={entry.seq} className="bench-log-line">
          <span className="bench-log-time">
            {new Date(entry.t * 1000).toLocaleTimeString([], { hour12: false })}
          </span>
          <span>{entry.line}</span>
        </div>
      ))}
    </section>
  )
}

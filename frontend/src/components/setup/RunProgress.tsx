// A status bar for a measurement run: how many of its steps are done, as a
// bar with the count, so a long run shows how far along it is.

export function RunProgress({ done, total, label }: { done: number; total: number; label?: string }) {
  if (total <= 0) return null
  const fraction = Math.min(Math.max(done / total, 0), 1)
  return (
    <div className="run-progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <div className="run-progress-bar">
        <div className="run-progress-fill" style={{ width: `${fraction * 100}%` }} />
      </div>
      <span className="run-progress-text">
        {done} / {total} · {Math.round(fraction * 100)}%{label ? ` · ${label}` : ''}
      </span>
    </div>
  )
}

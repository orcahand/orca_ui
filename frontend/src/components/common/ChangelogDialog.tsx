// The "What's new" dialog: the changelog document the backend ships, rendered
// over the console. Opens itself once per release (deferred while the hand is
// busy — see App) and otherwise sits behind the header button.

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useChangelogStore } from '../../state/changelogStore'
import { Markdown } from './Markdown'

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="cl-chip">
      <span className="cl-chip-label">{label}</span>
      <span className="cl-chip-value">{value}</span>
    </span>
  )
}

export function ChangelogDialog() {
  const { doc, isOpen, close } = useChangelogStore()
  const [suppress, setSuppress] = useState(true)

  // Ticked whenever the dialog opens: having read the notes, closing them is
  // the ordinary outcome. Unticking is the deliberate choice.
  useEffect(() => {
    if (isOpen) setSuppress(true)
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close(suppress)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, suppress, close])

  if (!isOpen || !doc) return null

  const behind =
    doc.latest_version && doc.ui_version !== doc.latest_version
      ? `running ${doc.ui_version}`
      : null

  return createPortal(
    <div className="cl-overlay" onClick={() => close(suppress)}>
      <div
        className="cl-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="What's new"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cl-header">
          <span className="cl-title">Changelog</span>
          {doc.latest_version ? <Chip label="ui" value={doc.latest_version} /> : null}
          {doc.recommended_core ? <Chip label="core" value={doc.recommended_core} /> : null}
          {behind ? <span className="cl-behind">{behind}</span> : null}
          <span className="cl-header-spacer" />
          <button className="btn btn-secondary" onClick={() => close(suppress)}>
            Close
          </button>
        </div>

        <div className="cl-body">
          {doc.markdown.trim() ? (
            <Markdown source={doc.markdown} />
          ) : (
            <p className="cl-empty">No changelog shipped with this build.</p>
          )}
        </div>

        <div className="cl-footer">
          <label className="cl-suppress">
            <input
              type="checkbox"
              checked={suppress}
              onChange={(e) => setSuppress(e.target.checked)}
            />
            <span>Don't show this again until the next update</span>
          </label>
        </div>
      </div>
    </div>,
    document.body,
  )
}

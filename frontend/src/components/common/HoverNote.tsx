// Progressive disclosure for instructions: a labelled trigger that reveals its
// detail on hover or keyboard focus. The panel is a child of the anchor, so
// the pointer can travel into it without dismissing it.
//
// Used wherever the full explanation would otherwise be a wall of text on
// arrival — the Setup cards keep their titles visible and hide the how/why
// behind these.

import { useId, type ReactNode } from 'react'

export function HoverNote({
  label,
  className,
  children,
}: {
  label: ReactNode
  // Extra class on the trigger: `note-title` for a step heading, omitted for
  // the plain inline form.
  className?: string
  children: ReactNode
}) {
  const id = useId()
  return (
    <span className="note-anchor">
      <button
        type="button"
        className={`note-trigger${className ? ` ${className}` : ''}`}
        aria-describedby={id}
      >
        <span className="note-label">{label}</span>
        <InfoMark />
      </button>
      <span className="note-pop" id={id} role="tooltip">
        {children}
      </span>
    </span>
  )
}

// Drawn rather than typeset: at 13px a font glyph sits off-centre in any box
// you put around it, and the console's type is Space Mono, whose "?" rides
// high. The geometry here is exact at every size.
function InfoMark() {
  return (
    <svg className="note-marker" viewBox="0 0 14 14" aria-hidden="true">
      <circle cx="7" cy="7" r="6.1" fill="none" stroke="currentColor" />
      <circle cx="7" cy="4.2" r="0.95" fill="currentColor" />
      <path
        d="M7 6.5v3.9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

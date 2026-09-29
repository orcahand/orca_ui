// Green/red presence dot. `on: undefined` (state not known yet) draws
// nothing, so panels never flash red before the first health payload.
// With a `diagnosis` it becomes clickable: the popover explains what is
// wrong and what to check.

import { Diagnosable, type Diagnosis } from './Diagnosable'

export function StatusDot({
  on,
  title,
  diagnosis,
}: {
  on?: boolean
  title?: string
  diagnosis?: Diagnosis
}) {
  if (on === undefined) return null
  const dot = (
    <span
      title={title}
      style={{
        width: 7,
        height: 7,
        borderRadius: '50%',
        background: on ? 'var(--ok)' : 'var(--err)',
        flexShrink: 0,
        display: 'inline-block',
        cursor: diagnosis ? 'pointer' : title ? 'help' : undefined,
      }}
    />
  )
  if (!diagnosis) return dot
  return (
    <Diagnosable
      diagnoses={[diagnosis]}
      label={`diagnose ${diagnosis.subject}`}
    >
      {dot}
    </Diagnosable>
  )
}

// Click-to-diagnose: wraps any electrical indicator (a status dot, a health
// count in the summary strip) so clicking it opens an anchored popover that
// names exactly what is broken and what to physically check. Complements the
// hover tooltips — a tooltip names the state, the popover explains it.

import { useEffect, useRef, useState, type ReactNode } from 'react'

export interface Diagnosis {
  // What the reader should look for on the bench: "index_pip joint sensor".
  subject: string
  // Current state, verbatim: "chip error", "not connected", "live"…
  state: string
  ok: boolean
  // Raw reason string from the health payload, when there is one.
  reason?: string | null
  // What to physically check, in the order worth trying.
  checks?: string[]
}

export function Diagnosable({
  diagnoses,
  children,
  label,
  align = 'left',
}: {
  diagnoses: Diagnosis[]
  children: ReactNode
  label?: string
  // 'right' anchors the popover to the right edge — for indicators sitting
  // near the viewport's right side.
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (anchor.current && !anchor.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (diagnoses.length === 0) return <>{children}</>

  return (
    <span ref={anchor} style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        aria-label={label ?? 'show diagnosis'}
        aria-expanded={open}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
        style={{
          all: 'unset',
          display: 'inline-flex',
          alignItems: 'center',
          cursor: 'pointer',
        }}
      >
        {children}
      </button>
      {open && (
        <span
          role="dialog"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            ...(align === 'right' ? { right: 0 } : { left: 0 }),
            zIndex: 40,
            width: 320,
            maxWidth: 'calc(100vw - 48px)',
            padding: '9px 11px',
            border: '1px solid rgb(var(--accent-rgb) / 0.35)',
            background: 'var(--pop-bg)',
            boxShadow: '0 8px 24px var(--pop-shadow-color)',
            fontSize: 10,
            lineHeight: 1.6,
            display: 'block',
          }}
        >
          {diagnoses.map((diagnosis, index) => (
            <span
              key={index}
              style={{
                display: 'block',
                paddingTop: index > 0 ? 8 : 0,
                marginTop: index > 0 ? 8 : 0,
                borderTop:
                  index > 0 ? '1px solid var(--panel-border)' : undefined,
              }}
            >
              <span
                style={{
                  display: 'flex',
                  gap: 6,
                  alignItems: 'baseline',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontWeight: 700, color: 'var(--text)' }}>
                  {diagnosis.subject}
                </span>
                <span
                  style={{
                    color: diagnosis.ok ? 'var(--ok)' : 'var(--err)',
                    fontWeight: 600,
                  }}
                >
                  {diagnosis.state}
                </span>
              </span>
              {diagnosis.reason && diagnosis.reason !== 'ok' && (
                <span style={{ display: 'block', color: 'var(--dim)' }}>
                  {diagnosis.reason}
                </span>
              )}
              {(diagnosis.checks?.length ?? 0) > 0 && (
                <span
                  style={{ display: 'block', color: 'var(--dim)', marginTop: 2 }}
                >
                  {diagnosis.checks!.map((check, i) => (
                    <span key={i} style={{ display: 'flex', gap: 5 }}>
                      <span style={{ color: 'var(--dimmer)' }}>▸</span>
                      <span>{check}</span>
                    </span>
                  ))}
                </span>
              )}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

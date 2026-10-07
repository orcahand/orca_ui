// Shared shell for the bench's two configuration popovers.
//
// A popover rather than an inline section: these write EEPROM that survives a
// power cycle, and two of the settings move a motor on the bus. They should
// take a deliberate click to reach, and close again when the work is done.

import { useEffect, useRef } from 'react'

export function RegisterPopover({
  title,
  warning,
  width,
  onClose,
  children,
}: {
  title: string
  warning: string
  width: number
  onClose: () => void
  children: React.ReactNode
}) {
  const ref = useRef<HTMLDivElement | null>(null)

  // Escape and click-away close it. Nothing here is committed by closing, so
  // leaving is always safe.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={title}
      style={{
        position: 'absolute',
        top: 'calc(100% + 6px)',
        left: 0,
        zIndex: 40,
        width,
        maxWidth: 'calc(100vw - 48px)',
        padding: '10px 12px',
        border: '1px solid rgb(var(--accent-rgb) / 0.35)',
        background: 'var(--pop-bg)',
        boxShadow: '0 8px 24px var(--pop-shadow-color)',
        fontSize: 10,
        lineHeight: 1.6,
        textAlign: 'left',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 6,
        }}
      >
        <b style={{ fontSize: 11 }}>{title}</b>
        <button
          className="btn btn-secondary"
          style={{ padding: '0 6px' }}
          onClick={onClose}
        >
          close
        </button>
      </div>
      <div style={{ color: 'var(--warn)', marginBottom: 8 }}>{warning}</div>
      {children}
    </div>
  )
}

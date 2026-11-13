// Which physical hand is connected, as a header chip that folds down its
// details: id and nickname, calibration date, joint ranges, and the previous
// calibration to go back to. Not modal: a click away or Escape folds it up.

import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../state/appStore'
import { HandDetails } from '../hand/HandDetails'
import { handLabel } from '../hand/handStore'

export function HandMenu() {
  const hand = useAppStore((s) => s.handInfo?.hand)
  const bare = useAppStore((s) => s.status?.bare ?? false)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  if (!hand || bare) return null
  return (
    <span className="model-picker hand-menu" ref={ref}>
      <button
        className="model-select hand-menu-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        title="This hand: id, nickname, calibration and joint ranges"
      >
        hand {handLabel(hand)} ▾
      </button>
      {open && (
        <div className="hand-menu-panel" role="region" aria-label="Connected hand">
          <HandDetails hand={hand} />
        </div>
      )}
    </span>
  )
}

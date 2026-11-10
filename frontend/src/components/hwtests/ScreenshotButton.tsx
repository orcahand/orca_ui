// Renders the open step panel to PNG, copies it to the clipboard and saves it
// in the step's screenshots folder. A refused clipboard still saves the file.

import { useState, type RefObject } from 'react'
import { toBlob } from 'html-to-image'
import { hwApi } from '../../api/hardwareTests'
import { useHardwareTestsStore } from '../../state/hardwareTestsStore'
import { usePalette } from '../../theme/themeStore'

// Elements marked hwt-no-shot (buttons, inputs) are left out of the picture.
function keep(node: HTMLElement): boolean {
  return !(node.classList && node.classList.contains('hwt-no-shot'))
}

export function ScreenshotButton({
  stepId,
  target,
}: {
  stepId: string
  target: RefObject<HTMLElement | null>
}) {
  const palette = usePalette()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ text: string; warn: boolean } | null>(null)

  const shoot = async () => {
    const node = target.current
    if (!node) return
    setBusy(true)
    setMessage(null)
    const rendering = toBlob(node, {
      backgroundColor: palette.bg,
      pixelRatio: Math.min(2, window.devicePixelRatio || 1),
      filter: keep,
    }).then((blob) => {
      if (!blob) throw new Error('the panel rendered to nothing')
      return blob
    })
    // The ClipboardItem takes the pending blob so the click still counts as
    // the user gesture by the time the image is ready.
    let clipboard: Promise<string | null>
    try {
      clipboard = navigator.clipboard
        .write([new ClipboardItem({ 'image/png': rendering })])
        .then(() => null)
        .catch((error: unknown) => String((error as Error).message ?? error))
    } catch (error) {
      clipboard = Promise.resolve(String((error as Error).message ?? error))
    }
    try {
      const blob = await rendering
      const { file } = await hwApi.screenshot(stepId, blob)
      const refused = await clipboard
      setMessage({
        text: refused
          ? `saved ${file} · not copied: ${refused}`
          : `saved ${file} · copied to the clipboard`,
        warn: refused !== null,
      })
      void useHardwareTestsStore.getState().refresh()
    } catch (error) {
      setMessage({
        text: `screenshot failed: ${String((error as Error).message ?? error)}`,
        warn: true,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="hwt-shot hwt-no-shot">
      <button className="btn btn-scan" disabled={busy} onClick={() => void shoot()}>
        {busy ? 'Capturing…' : 'Screenshot'}
      </button>
      {message && <span className={`hwt-hint${message.warn ? ' warn' : ''}`}>{message.text}</span>}
    </span>
  )
}

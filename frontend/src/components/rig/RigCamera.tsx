// The rig camera on the dashboard (docs/rig-dashboard.md): the backend's preview (it owns the
// cameras) turned like the visual-calibration page (270° by default, its camera choice), and on request the model
// overlay: the hand at its live pose (study-corrected when the study map is on) and the
// tower's tiles at the plate angle. Off by default; click to enlarge, Esc to close.

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useRig } from '../../state/rigStore'
import { visualApi, type ModelOverlay } from '../visual/api'
import { drawTiles } from '../visual/drawTiles'
import { usePageVisible } from '../common/usePageVisible'
import { useBackendCamera } from '../visual/backendCamera'
import type { HandOverlay } from '../visual/handOverlay'

const CAMERA_KEY = 'orca-ui.visual-calibration.camera'
const ROTATION_KEY = 'orca-ui.visual-calibration.rotation'
const ACCENT = '#22d3ee'
const NO_LETTERS: Record<string, string> = {}

function stored<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}

export function RigCamera() {
  const camera = useRig((s) => s.camera)
  const overlay = useRig((s) => s.overlay)
  const info = useRig((s) => s.info)
  const letters = info?.letters ?? NO_LETTERS
  const angle = useRig((s) => s.twinState?.angle ?? null)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const video = useRef<HTMLVideoElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [zoomed, setZoomed] = useState(false)
  const [model, setModel] = useState<ModelOverlay | null>(null)
  const hand = useRef<HandOverlay | null>(null)
  const rotation = stored<number>(ROTATION_KEY, 270)

  useEffect(() => {
    if (!zoomed) return
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setZoomed(false)
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [zoomed])

  const pageVisible = usePageVisible()
  const saved = stored<string>(CAMERA_KEY, 'a')
  const shown = (info?.cameras ?? ['a']).includes(saved) ? saved : 'a'
  const { stream, error } = useBackendCamera(camera ? shown : null, pageVisible)
  useEffect(() => {
    const v = video.current
    if (!v) return
    v.srcObject = stream
    if (stream) void v.play().catch(() => undefined)
  }, [stream])

  // The overlay's model (lens, camera_from_plate, tiles) at the plate angle, refetched as it turns.
  const key = angle === null ? null : Math.round(angle * 2) / 2
  useEffect(() => {
    if (!camera || !overlay) return
    let alive = true
    visualApi.overlay(key ?? 0, rotation, shown).then((m) => alive && setModel(m)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [camera, overlay, key, rotation, shown])

  useEffect(() => {
    if (!camera || !overlay || !joints) return
    let alive = true
    Promise.all([api.modelMetadata(), import('../visual/handOverlay')])
      .then(([meta, mod]) => mod.HandOverlay.create(meta.urdf_url, joints, ACCENT))
      .then((h) => {
        if (!alive) return h.dispose()
        hand.current = h
      })
      .catch(() => undefined)
    return () => {
      alive = false
      hand.current?.dispose()
      hand.current = null
    }
  }, [camera, overlay, joints])

  const modelRef = useRef(model)
  modelRef.current = model
  const lettersRef = useRef(letters)
  lettersRef.current = letters
  useEffect(() => {
    if (!camera) return
    let raf = 0
    const draw = () => {
      const v = video.current
      const c = canvas.current
      const ctx = c?.getContext('2d')
      if (v && c && ctx && v.videoWidth) {
        const W = v.videoWidth
        const H = v.videoHeight
        const side = rotation === 90 || rotation === 270
        const w = side ? H : W
        const h = side ? W : H
        if (c.width !== w || c.height !== h) {
          c.width = w
          c.height = h
        }
        const a = (rotation * Math.PI) / 180
        ctx.setTransform(1, 0, 0, 1, w / 2, h / 2)
        ctx.rotate(a)
        ctx.drawImage(v, -W / 2, -H / 2)
        const m = modelRef.current
        if (overlay && m) {
          const hd = hand.current
          if (hd) {
            hd.place(m)
            hd.setPose(null) // the live stream: study-mapped server-side when a map is on
            const k = Math.min(1, 960 / Math.max(W, H))
            const img = hd.render(Math.round(W * k), Math.round(H * k))
            ctx.globalAlpha = 0.9
            if (img) ctx.drawImage(img, -W / 2, -H / 2, W, H)
            ctx.globalAlpha = 1
          }
          const px = c.width / Math.max(1, c.clientWidth)
          drawTiles(ctx, m, W, H, a, w, h, px, { color: ACCENT, opacity: 0.9 }, lettersRef.current)
        }
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [camera, overlay, rotation])

  if (!camera) return null
  const frame = (
    <div
      className={zoomed ? 'visual-cal-zoom' : 'visual-cal-frame rig-camera-frame'}
      onClick={() => setZoomed((z) => !z)}
      title={zoomed ? 'Click or Esc to close' : 'Click to enlarge'}
    >
      <canvas ref={canvas} className="visual-cal-video" />
      {error && <span className="visual-cal-seg-note">{error}</span>}
      {zoomed && angle !== null && <span className="visual-cal-zoom-caption">plate {angle.toFixed(1)}°</span>}
    </div>
  )
  // Enlarged, it portals to <body>: the dashboard's sticky column would trap its z-index.
  return (
    <>
      <video ref={video} muted playsInline style={{ display: 'none' }} />
      {zoomed ? createPortal(frame, document.body) : frame}
    </>
  )
}

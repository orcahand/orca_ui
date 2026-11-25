// The rig cameras on the dashboard (docs/rig-dashboard.md): every enabled camera's live stream,
// each turned like on the visual-calibration page (its turn and device choice; cam A 270°, cam B
// 90° by default), its identity checked against the camera's USB serial, and on request the
// model overlay: the hand at its live pose (study-corrected when the study map is on) and the
// tower's tiles at the plate angle, from that camera's pose. Off by default; click a view to
// enlarge it, Esc to close.

import { useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useRig } from '../../state/rigStore'
import { CAMS, visualApi, type CamId, type ModelOverlay } from '../visual/api'
import { drawTiles } from '../visual/drawTiles'
import { CAM_LABEL, useRigCameras, type CamFeed } from '../visual/useRigCameras'
import { UsbBanner } from '../visual/UsbBanner'
import type { HandOverlay } from '../visual/handOverlay'

const ROTATION_KEY = 'orca-ui.visual-calibration.rotation'
const DEFAULT_ROTATION: Record<CamId, number> = { a: 270, b: 90 }
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

function CameraView({
  feed,
  rotation,
  overlay,
  hand,
}: {
  feed: CamFeed
  rotation: number
  overlay: boolean
  hand: RefObject<HandOverlay | null>
}) {
  const cam = feed.cam
  const info = useRig((s) => s.info)
  const letters = info?.letters ?? NO_LETTERS
  const angle = useRig((s) => s.twinState?.angle ?? null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [zoomed, setZoomed] = useState(false)
  const [model, setModel] = useState<ModelOverlay | null>(null)

  useEffect(() => {
    if (!zoomed) return
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setZoomed(false)
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [zoomed])

  // This camera's model (lens, camera_from_plate, tiles) at the plate angle, refetched as it turns.
  const key = angle === null ? null : Math.round(angle * 2) / 2
  useEffect(() => {
    if (!overlay) return
    let alive = true
    visualApi.overlay(key ?? 0, rotation, cam).then((m) => alive && setModel(m)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [overlay, key, rotation, cam])

  const modelRef = useRef(model)
  modelRef.current = model
  const lettersRef = useRef(letters)
  lettersRef.current = letters
  const video = feed.video
  useEffect(() => {
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
  }, [overlay, rotation, video, hand])

  const unsure = feed.identity === 'mismatch' || feed.identity === 'unknown'
  const frame = (
    <div
      className={zoomed ? 'visual-cal-zoom' : 'visual-cal-frame rig-camera-frame'}
      onClick={() => setZoomed((z) => !z)}
      title={zoomed ? 'Click or Esc to close' : 'Click to enlarge'}
    >
      <canvas ref={canvas} className="visual-cal-video" />
      <span className="visual-cal-cam-label" title={feed.identityNote ?? ''}>
        <b>{CAM_LABEL[cam]}</b>
        {unsure ? ` · ${feed.identityNote ?? 'identity unknown'}` : feed.identity === 'ok' ? ' · serial ✓' : ''}
      </span>
      {feed.error && <span className="visual-cal-seg-note">{feed.error}</span>}
      {zoomed && angle !== null && (
        <span className="visual-cal-zoom-caption">
          {CAM_LABEL[cam]} · plate {angle.toFixed(1)}°
        </span>
      )}
    </div>
  )
  // Enlarged, it portals to <body>: the dashboard's sticky column would trap its z-index.
  return zoomed ? createPortal(frame, document.body) : frame
}

export function RigCamera() {
  const camera = useRig((s) => s.camera)
  const overlay = useRig((s) => s.overlay)
  const info = useRig((s) => s.info)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const hand = useRef<HandOverlay | null>(null)
  const cams = (info?.active_cameras ?? ['a']).filter((c): c is CamId => (CAMS as readonly string[]).includes(c))
  // The rig cameras' own mode (4K, useRigCameras): a smaller request switches the device for every
  // client and starves the study's 4K capture; the canvas scales it down.
  const { feeds, access, sources } = useRigCameras(cams, camera)

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

  if (!camera) return null
  const rotation = (c: CamId) =>
    stored<number>(c === 'a' ? ROTATION_KEY : `${ROTATION_KEY}.${c}`, info?.cameras?.[c]?.rotation ?? DEFAULT_ROTATION[c])
  return (
    <>
      {sources}
      {access && <span className="visual-cal-seg-note">{access}</span>}
      <UsbBanner />
      <div className="rig-cameras">
        {cams.map((c) => (
          <CameraView key={c} feed={feeds[c]} rotation={rotation(c)} overlay={overlay} hand={hand} />
        ))}
      </div>
    </>
  )
}

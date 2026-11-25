// The rig's cameras in the browser: one getUserMedia stream per enabled camera (a, b), each
// bound to a browser device. Both BRIOs report the same label and the device order is not
// identity, so every stream is checked against the server, which takes a still of each camera
// by its USB serial (POST /camera/identify): a stream that shows the other camera swaps the two
// assignments, one it cannot place stays "unknown" and captures from it are refused. Streams
// stop while the tab is hidden and ask for 4K: a smaller request switches the device's mode
// for every client (the study's 4K capture too).

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { usePageVisible } from '../common/usePageVisible'
import { CAMS, grabFrame, visualApi, type CamId } from './api'

const CAMERAS_KEY = 'orca-ui.visual-calibration.cameras'
const LEGACY_CAMERA_KEY = 'orca-ui.visual-calibration.camera'
const PREFERRED = /brio/i
const SETTLE_MS = 1200 // let a new stream's exposure settle before comparing it
const MAX_SWAPS = 2

export type Identity = 'off' | 'checking' | 'ok' | 'mismatch' | 'unknown' | 'mock'

export interface CamFeed {
  cam: CamId
  deviceId: string
  stream: MediaStream | null
  playing: boolean
  size: string | null
  error: string | null
  identity: Identity
  identityNote: string | null
  video: RefObject<HTMLVideoElement | null>
}

export const CAM_LABEL: Record<CamId, string> = { a: 'cam A', b: 'cam B' }

/** A stream from this camera may be stored: its view matched the camera's serial (or --mock). */
export const trusted = (f: CamFeed | undefined) => !!f && (f.identity === 'ok' || f.identity === 'mock')

function storedIds(): Partial<Record<CamId, string>> {
  try {
    const v = JSON.parse(localStorage.getItem(CAMERAS_KEY) ?? 'null') as Partial<Record<CamId, string>> | null
    if (v) return v
    const legacy = localStorage.getItem(LEGACY_CAMERA_KEY)
    return legacy ? { a: JSON.parse(legacy) as string } : {}
  } catch {
    return {}
  }
}

function storeIds(ids: Partial<Record<CamId, string>>) {
  try {
    localStorage.setItem(CAMERAS_KEY, JSON.stringify(ids))
    if (ids.a) localStorage.setItem(LEGACY_CAMERA_KEY, JSON.stringify(ids.a))
  } catch {
    /* private mode */
  }
}

/** Saved devices where still present, then BRIOs, then anything, never one device twice. */
function pick(devices: MediaDeviceInfo[], saved: Partial<Record<CamId, string>>, cams: readonly CamId[]) {
  const out: Partial<Record<CamId, string>> = {}
  const used = new Set<string>()
  for (const c of cams) {
    const id = saved[c]
    if (id && devices.some((d) => d.deviceId === id) && !used.has(id)) {
      out[c] = id
      used.add(id)
    }
  }
  const rest = [...devices.filter((d) => PREFERRED.test(d.label)), ...devices.filter((d) => !PREFERRED.test(d.label))]
  for (const c of cams) {
    if (out[c]) continue
    const d = rest.find((x) => !used.has(x.deviceId))
    if (d) {
      out[c] = d.deviceId
      used.add(d.deviceId)
    }
  }
  return out
}

function useFeed(cam: CamId, deviceId: string, on: boolean) {
  const video = useRef<HTMLVideoElement | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [playing, setPlaying] = useState(false)
  const [size, setSize] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!deviceId || !on) return
    let opened: MediaStream | null = null
    let alive = true
    setSize(null)
    navigator.mediaDevices
      .getUserMedia({ video: { deviceId: { exact: deviceId }, width: { ideal: 3840 }, height: { ideal: 2160 } } })
      .then((s) => {
        if (!alive) return s.getTracks().forEach((t) => t.stop())
        opened = s
        setStream(s)
        setError(null)
        const st = s.getVideoTracks()[0]?.getSettings()
        if (st?.width) setSize(`${st.width}×${st.height}${st.frameRate ? ` · ${Math.round(st.frameRate)} fps` : ''}`)
      })
      .catch((e: Error) => alive && setError(`${CAM_LABEL[cam]}: could not open the camera: ${e.message}`))
    return () => {
      alive = false
      opened?.getTracks().forEach((t) => t.stop())
      setStream(null)
    }
  }, [cam, deviceId, on])

  useEffect(() => {
    const v = video.current
    setPlaying(false)
    if (!v || !stream) return
    v.srcObject = stream
    const ready = () => setPlaying(true)
    v.addEventListener('loadeddata', ready)
    void v.play().catch(() => undefined)
    return () => {
      v.removeEventListener('loadeddata', ready)
      v.srcObject = null
    }
  }, [stream])

  return { video, stream: deviceId && on ? stream : null, playing: !!stream && playing, size, error: deviceId && on ? error : null }
}

type Feed = ReturnType<typeof useFeed>

/** Which camera a new stream shows, by the serials (POST /camera/identify), once its exposure settled. */
function useIdentity(
  cam: CamId,
  feed: Feed,
  deviceId: string,
  wanted: string,
  nonce: number,
  swap: (cam: CamId, other: CamId, deviceId: string) => boolean,
): { state: Identity; note: string | null } {
  const [state, setState] = useState<{ state: Identity; note: string | null }>({ state: 'checking', note: null })
  const { playing, stream, video } = feed
  useEffect(() => {
    if (!playing || !stream) return
    let alive = true
    setState({ state: 'checking', note: null })
    const cams = wanted.split(',')
    const timer = window.setTimeout(async () => {
      const v = video.current
      if (!alive || !v?.videoWidth) return
      try {
        const r = await visualApi.identify(await grabFrame(v, 'image/jpeg', 640), cam)
        if (!alive) return
        const scores = Object.entries(r.scores)
          .map(([k, x]) => `${k} ${x?.toFixed(2)}`)
          .join(', ')
        const errors = Object.values(r.errors).join('; ')
        if (r.mock) setState({ state: 'mock', note: 'not checked (--mock)' })
        else if (r.camera === cam) setState({ state: 'ok', note: `matches its serial (${scores})` })
        else if (r.camera && cams.includes(r.camera) && swap(cam, r.camera, deviceId))
          setState({ state: 'checking', note: `this device is ${CAM_LABEL[r.camera]}: swapped` })
        else if (r.camera)
          setState({ state: 'mismatch', note: `this device shows ${CAM_LABEL[r.camera]}, not ${CAM_LABEL[cam]}: pick the other camera` })
        else
          setState({
            state: 'unknown',
            note: `can’t tell which camera this is${scores ? ` (${scores})` : ''}${errors ? `: ${errors}` : ''}`,
          })
      } catch (e) {
        if (alive) setState({ state: 'unknown', note: `identity check failed: ${(e as Error).message}` })
      }
    }, SETTLE_MS)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [cam, playing, stream, video, deviceId, wanted, nonce, swap])
  return state
}

/**
 * Streams for `cams` (the enabled cameras, a first) while `on` and the tab is visible.
 * Render `sources` once: the hidden <video> elements the views draw from.
 */
export function useRigCameras(cams: readonly CamId[], on: boolean) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [ids, setIds] = useState<Partial<Record<CamId, string>>>(storedIds)
  const [access, setAccess] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const swaps = useRef(0)
  const visible = usePageVisible()
  const live = on && visible
  const wanted = cams.join(',')

  // Labels are only readable once camera access is granted. The access probe opens a camera at its
  // default mode, which switches the device for every client: only probe while labels are hidden.
  useEffect(() => {
    if (!on) return
    let alive = true
    const list = async () => {
      const all = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
      if (alive) setDevices(all)
    }
    navigator.mediaDevices
      .enumerateDevices()
      .then((all) =>
        all.some((d) => d.kind === 'videoinput' && d.label)
          ? list()
          : navigator.mediaDevices.getUserMedia({ video: true }).then((probe) => {
              probe.getTracks().forEach((t) => t.stop())
              return list()
            }),
      )
      .catch((e: Error) => alive && setAccess(`No camera access: ${e.message}`))
    navigator.mediaDevices.addEventListener('devicechange', list)
    return () => {
      alive = false
      navigator.mediaDevices.removeEventListener('devicechange', list)
    }
  }, [on])

  // Keep the assignment valid for the devices there now.
  useEffect(() => {
    if (!devices.length) return
    setIds((cur) => {
      const cams = wanted.split(',') as CamId[]
      const next = pick(devices, cur, cams)
      const same = cams.every((c) => (next[c] ?? '') === (cur[c] ?? ''))
      if (same) return cur
      const merged = { ...cur, ...next }
      storeIds(merged)
      return merged
    })
  }, [devices, wanted])

  const want = (c: CamId) => cams.includes(c)
  const a = useFeed('a', want('a') ? (ids.a ?? '') : '', live)
  const b = useFeed('b', want('b') ? (ids.b ?? '') : '', live)
  const raw = { a, b }

  const assign = useCallback((cam: CamId, deviceId: string) => {
    swaps.current = 0
    setIds((cur) => {
      const other = CAMS.find((c) => c !== cam && cur[c] === deviceId)
      const next = { ...cur, [cam]: deviceId, ...(other ? { [other]: cur[cam] ?? '' } : {}) }
      storeIds(next)
      return next
    })
  }, [])

  const verify = useCallback(() => {
    swaps.current = 0
    setNonce((n) => n + 1)
  }, [])

  // A stream showed `other`: swap the two (unless the assignment moved on since the check).
  const idsRef = useRef(ids)
  idsRef.current = ids
  const swap = useCallback((cam: CamId, other: CamId, deviceId: string): boolean => {
    const cur = idsRef.current
    if (cur[cam] !== deviceId) return true
    if (swaps.current >= MAX_SWAPS) return false
    swaps.current += 1
    const next = { ...cur, [cam]: cur[other] ?? '', [other]: deviceId }
    idsRef.current = next
    storeIds(next)
    setIds(next)
    return true
  }, [])
  const ida = useIdentity('a', a, ids.a ?? '', wanted, nonce, swap)
  const idb = useIdentity('b', b, ids.b ?? '', wanted, nonce, swap)
  const identity = { a: ida, b: idb }

  const feeds = Object.fromEntries(
    CAMS.map((c) => [
      c,
      {
        cam: c,
        deviceId: ids[c] ?? '',
        ...raw[c],
        error: raw[c].error ?? (want(c) && devices.length && !ids[c] ? `${CAM_LABEL[c]}: no free camera` : null),
        identity: raw[c].stream ? identity[c].state : 'off',
        identityNote: raw[c].stream ? identity[c].note : null,
      } satisfies CamFeed,
    ]),
  ) as Record<CamId, CamFeed>

  const sources = (
    <>
      {CAMS.map((c) => (
        <video key={c} ref={raw[c].video} className="visual-cal-source" autoPlay playsInline muted />
      ))}
    </>
  )
  return { devices, feeds, access, assign, verify, sources }
}

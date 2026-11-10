// Reading a solve: its fit, whether it is good, and the camera as the rig config's mount describes it.

import type { CameraMount, Fit, Session, SolveResult } from './api'

export const GOOD_PX = 0.5
export const PHOTO_PX = 1

export const fitOf = (r: SolveResult): Fit | undefined => r.fit ?? r.camera_fit

export function solvedWell(s: Session | null): boolean {
  const r = s?.result
  const fit = r && fitOf(r)
  if (!r || !fit) return false
  const photos = Object.values(r.per_photo_px)
  return fit.reprojection_px <= GOOD_PX && (s!.step === 'camera' || !photos.length || Math.max(...photos) <= PHOTO_PX)
}

// The solved camera as the rig config describes its mount: lens distance from
// the axis, height above the plate, tilt down. Rotation is R = Rz Ry Rx
// (camera -> rig), so the optical axis' z is cos(roll) cos(pitch).
export function mountOf(r: SolveResult): CameraMount | null {
  if (!r.camera) return null
  const [x, y, z] = r.camera.translation
  const [roll, pitch] = r.camera.rotation.map((d) => (d * Math.PI) / 180)
  const down = -Math.cos(roll) * Math.cos(pitch)
  return { distance: Math.hypot(x, y), height: z, tilt: (Math.asin(Math.max(-1, Math.min(1, down))) * 180) / Math.PI }
}

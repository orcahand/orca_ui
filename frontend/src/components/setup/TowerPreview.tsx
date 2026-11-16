// The tower with its hulls off, one view per face, every spool coloured by
// how far its motor followed the joint in the last range check and tagged
// with motor id, joint and score — so the operator sees which spools still
// need the ratchet. Each face is a picture rendered from the CAD assembly
// (tower_<face>.png beside the model, with tower_faces.json saying where each
// spool sits in it), overlaid with a box the size of the spool in the spool's
// colour; a model without the pictures falls back to the live 3D view.
// `tags="motor"` leaves the score off each spool for a view that has its own
// list beside it; motor id and joint are always shown.

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { MotorSpread } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { FACE_LABEL, spoolJoint, type TowerFace } from './towerLayout'

const FaceCanvas = lazy(() => import('./TowerFaceCanvas').then((m) => ({ default: m.FaceCanvas })))

export type TagStyle = 'full' | 'motor'

// What a spool needs to be coloured and tagged: a guided-tensioning row, or
// any other per-joint finding with a status and a short text.
export type SpoolMark = Pick<MotorSpread, 'joint' | 'motor' | 'status' | 'fraction'> & { tag?: string }

export type Side = 'left' | 'right'

interface FaceImage {
  width: number
  height: number
  spools: Record<string, { x: number; y: number; w: number; h: number }>
}

const faceImages = new Map<string, Promise<Record<string, FaceImage> | null>>()
function loadFaceImages(side: Side): Promise<Record<string, FaceImage> | null> {
  if (!faceImages.has(side)) {
    faceImages.set(
      side,
      fetch(`/assets/hand/${side}/tower_faces.json`)
        .then((r) => (r.ok ? (r.json() as Promise<Record<string, FaceImage>>) : null))
        .catch(() => null),
    )
  }
  return faceImages.get(side)!
}

// The rendered picture with a box over each spool, fitted like the picture itself.
function FaceImageView({
  side,
  face,
  byJoint,
  tags,
  image,
}: {
  side: Side
  face: TowerFace
  byJoint: Record<string, SpoolMark>
  tags: TagStyle
  image: FaceImage
}) {
  const motorIds = useMotorIds()
  const [box, setBox] = useState<{ left: number; top: number; width: number; height: number } | null>(null)
  const holder = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = holder.current
    if (!el) return
    const fit = () => {
      // object-fit: contain — the drawn picture sits centred inside the element.
      const scale = Math.min(el.clientWidth / image.width, el.clientHeight / image.height)
      const width = image.width * scale
      const height = image.height * scale
      setBox({ left: (el.clientWidth - width) / 2, top: (el.clientHeight - height) / 2, width, height })
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [image])
  return (
    <div className="tower-image" ref={holder}>
      <img src={`/assets/hand/${side}/tower_${face}.png`} alt={`${FACE_LABEL[face]} of the tower`} draggable={false} />
      {box &&
        Object.entries(image.spools).map(([pos, r]) => {
          const joint = spoolJoint(side, pos)
          const motor = byJoint[joint]
          const status = motor?.status ?? 'unscored'
          return (
            <div
              key={pos}
              className={`tower-spool ${status}`}
              style={{
                left: box.left + r.x * box.width,
                top: box.top + r.y * box.height,
                width: r.w * box.width,
                height: r.h * box.height,
              }}
              title={`${joint}${motor?.tag ? ` · ${motor.tag}` : ''}`}
            >
              <b>M{motor?.motor || motorIds[joint] || '?'}</b>
              <span className={`tower-spool-label ${r.x + r.w / 2 < 0.5 ? 'left' : 'right'}`}>
                {joint.replace('_', ' ')}
                {tags === 'full' && motor?.tag ? ` · ${motor.tag}` : ''}
              </span>
            </div>
          )
        })}
    </div>
  )
}

export function FaceView({
  side,
  face,
  byJoint,
  tags = 'full',
}: {
  side: Side
  face: TowerFace
  byJoint: Record<string, SpoolMark>
  tags?: TagStyle
}) {
  const [images, setImages] = useState<Record<string, FaceImage> | null | undefined>(undefined)
  useEffect(() => {
    let alive = true
    loadFaceImages(side).then((found) => alive && setImages(found))
    return () => {
      alive = false
    }
  }, [side])
  if (images === undefined) return <div className="gt-tower-face" />
  if (images && images[face]) {
    return (
      <div className="gt-tower-face">
        <div className="gt-tower-face-title">{FACE_LABEL[face]}</div>
        <FaceImageView side={side} face={face} byJoint={byJoint} tags={tags} image={images[face]} />
      </div>
    )
  }
  return (
    <div className="gt-tower-face">
      <div className="gt-tower-face-title">{FACE_LABEL[face]}</div>
      <ErrorBoundary label="The tower view" fallback={() => null}>
        <Suspense fallback={null}>
          <FaceCanvas side={side} face={face} byJoint={byJoint} tags={tags} />
        </Suspense>
      </ErrorBoundary>
    </div>
  )
}

// Each joint's motor from the hand's config, for spools no result has marked yet.
export function useMotorIds(): Record<string, number> {
  const joints = useAppStore((s) => s.handInfo?.joints)
  return useMemo(
    () => Object.fromEntries((joints ?? []).filter((j) => j.motor_id != null).map((j) => [j.id, j.motor_id as number])),
    [joints],
  )
}

export function useSpoolMarks(motors: SpoolMark[]): Record<string, SpoolMark> {
  const key = motors.map((m) => `${m.joint}:${m.status}:${m.fraction}:${m.tag ?? ''}`).join(',')
  return useMemo(
    () => Object.fromEntries(motors.map((m) => [m.joint, m])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  )
}

export function TowerPreview({ motors, tags = 'full' }: { motors: SpoolMark[]; tags?: TagStyle }) {
  const byJoint = useSpoolMarks(motors)
  const side = useAppStore((s) => s.handInfo?.side) ?? 'right'
  return (
    <div className="gt-tower">
      <FaceView side={side} face="F" byJoint={byJoint} tags={tags} />
      <FaceView side={side} face="B" byJoint={byJoint} tags={tags} />
    </div>
  )
}

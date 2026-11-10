// The tower with its hulls off, one view per face, every spool coloured by
// how far its motor followed the joint in the last range check and tagged
// with motor id, joint and score — so the operator sees which spools still
// need the ratchet. Each face is a picture rendered from the CAD assembly
// (tower_<face>.png beside the model, with tower_faces.json saying where each
// spool sits in it), overlaid with a box the size of the spool in the spool's
// colour; a model without the pictures falls back to the live 3D view.
// `tags="motor"` leaves the score off each spool for a view that has its own
// list beside it; motor id and joint are always shown.

import { Canvas, useThree } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { MotorSpread, SpreadStatus } from '../../api/types'
import { usePalette } from '../../theme/themeStore'
import { useAppStore } from '../../state/appStore'
import { StudioLights } from '../three/StudioLights'
import { FACE_LABEL, spoolJoint, towerUrl, type TowerFace } from './towerLayout'

const SPOOL_COLOUR: Record<SpreadStatus, number> = {
  pass: 0x34b37a,
  unconfirmed: 0x22d3ee,
  slack: 0xe0565b,
  partial: 0xf2b134,
  low: 0xe0565b,
  unscored: 0xb8bec6,
  fault: 0xb02a4a,
}
// Matte product-render look for the printed parts.
const PART_COLOUR: Record<string, number> = { structure: 0xd9dcdf, motor: 0x4b5158, hand: 0xf1f2f3 }
export type TagStyle = 'full' | 'motor'
// How much of the wrist shows above the tower, in metres of model space.
const HAND_ABOVE_TOWER = 0.035


const towers = new Map<string, Promise<THREE.Group>>()
function loadTower(url: string): Promise<THREE.Group> {
  if (!towers.has(url)) towers.set(url, new GLTFLoader().loadAsync(url).then((gltf) => gltf.scene))
  return towers.get(url)!
}

// What a spool needs to be coloured and tagged: a guided-tensioning row, or
// any other per-joint finding with a status and a short text.
export type SpoolMark = Pick<MotorSpread, 'joint' | 'motor' | 'status' | 'fraction'> & { tag?: string }

interface SpoolTag {
  pos: string
  joint: string
  motor: SpoolMark | undefined
  at: THREE.Vector3
}

type Side = 'left' | 'right'

function FaceRig({
  side,
  face,
  byJoint,
  tags: tagStyle,
}: {
  side: Side
  face: TowerFace
  byJoint: Record<string, SpoolMark>
  tags: TagStyle
}) {
  const url = towerUrl(side)
  const [root, setRoot] = useState<THREE.Group | null>(null)
  const camera = useThree((s) => s.camera) as THREE.OrthographicCamera
  const controls = useThree((s) => s.controls) as { target: THREE.Vector3; update: () => void } | null
  const size = useThree((s) => s.size)
  const invalidate = useThree((s) => s.invalidate)
  const sign = face === 'B' ? 1 : -1

  useEffect(() => {
    let alive = true
    loadTower(url).then((scene) => {
      if (!alive) return
      const clone = scene.clone(true)
      clone.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (!mesh.isMesh) return
        const material = (mesh.material as THREE.MeshStandardMaterial).clone()
        const part = o.name.split('_')[0]
        if (PART_COLOUR[part] !== undefined) material.color.setHex(PART_COLOUR[part])
        material.roughness = 0.75
        material.metalness = 0
        material.envMapIntensity = 0.5
        mesh.material = material
        mesh.castShadow = true
      })
      // The fingers would dwarf the spools: keep only the wrist above the tower.
      const tower = new THREE.Box3()
      clone.traverse((o) => {
        if ((o as THREE.Mesh).isMesh && !o.name.startsWith('hand')) tower.expandByObject(o)
      })
      const cut = tower.max.y + HAND_ABOVE_TOWER
      clone.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (mesh.isMesh && o.name.startsWith('hand')) {
          ;(mesh.material as THREE.MeshStandardMaterial).clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, -1, 0), cut)]
        }
      })
      clone.userData.fit = tower.clone().expandByVector(new THREE.Vector3(0, 0, 0))
      clone.userData.fit.max.y = cut
      setRoot(clone)
    })
    return () => {
      alive = false
    }
  }, [url])

  useEffect(() => {
    if (!root || !controls) return
    // Fit the tower with its spools and the wrist stub to the canvas, straight
    // on, refitted whenever the canvas changes size.
    const box = (root.userData.fit as THREE.Box3 | undefined) ?? new THREE.Box3().setFromObject(root)
    if (box.isEmpty()) return
    const centre = box.getCenter(new THREE.Vector3())
    const extent = box.getSize(new THREE.Vector3())
    const pad = 1.08
    camera.left = -size.width / 2
    camera.right = size.width / 2
    camera.top = size.height / 2
    camera.bottom = -size.height / 2
    camera.zoom = Math.min(size.width / (extent.x * pad), size.height / (extent.y * pad))
    const distance = extent.length()
    camera.position.copy(centre).add(new THREE.Vector3(0, 0, sign * distance))
    camera.near = 0.001
    camera.far = distance * 4
    camera.updateProjectionMatrix()
    controls.target.copy(centre)
    controls.update()
    invalidate()
  }, [root, controls, camera, size.width, size.height, sign, invalidate])

  const tags = useMemo<SpoolTag[]>(() => {
    if (!root) return []
    const out: SpoolTag[] = []
    root.traverse((o) => {
      const match = /^spool_([FB]\d\d)/.exec(o.name)
      if (!match || !(o as THREE.Mesh).isMesh) return
      const pos = match[1]
      const joint = spoolJoint(side, pos)
      const motor = byJoint[joint]
      const material = (o as THREE.Mesh).material as THREE.MeshStandardMaterial
      const colour = SPOOL_COLOUR[motor?.status ?? 'unscored']
      material.color.setHex(colour)
      material.emissive.setHex(colour)
      material.emissiveIntensity = motor && motor.status !== 'pass' && motor.status !== 'unscored' ? 0.2 : 0.05
      if (pos[0] === face) {
        out.push({ pos, joint, motor, at: new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3()) })
      }
    })
    invalidate()
    return out
  }, [root, byJoint, face, side, invalidate])

  if (!root) return null
  return (
    <>
      <primitive object={root} />
      {tags.map((tag) => (
        <Html key={tag.pos} position={tag.at} center zIndexRange={[10, 0]}>
          <div className={`gt-spool-tag ${tagStyle} ${tag.motor?.status ?? 'unscored'}`}>
            {tagStyle === 'motor' ? (
              <>
                <b>M{tag.motor?.motor ?? '?'}</b>
                <small>{tag.joint}</small>
              </>
            ) : (
              <>
                <span>
                  <b>M{tag.motor?.motor ?? '?'}</b>{' '}
                  {tag.motor?.tag ?? (tag.motor?.fraction == null ? '—' : `${Math.round(tag.motor.fraction * 100)}%`)}
                </span>
                <small>{tag.joint}</small>
              </>
            )}
          </div>
        </Html>
      ))}
    </>
  )
}

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
  const { scene } = usePalette()
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
      <Canvas
        frameloop="demand"
        orthographic
        dpr={[1, 2]}
        gl={{ antialias: true, localClippingEnabled: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.0 }}
        camera={{ zoom: 1000, position: [0, 0, 1], near: 0.001, far: 10 }}
        style={{ background: scene.bg }}
      >
        <StudioLights shadowScale={0.5} shadowY={-0.06} />
        <OrbitControls makeDefault enableDamping={false} enableRotate={false} />
        <FaceRig side={side} face={face} byJoint={byJoint} tags={tags} />
      </Canvas>
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

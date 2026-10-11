// The tower with its hulls off, one view per face, every spool coloured by
// how far its motor followed the joint in the last range check and tagged
// with motor id, joint and score — so the operator sees which spools still
// need the ratchet.

import { Canvas, useThree } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { MotorSpread, SpreadStatus } from '../../api/types'
import { usePalette } from '../../theme/themeStore'
import { useAppStore } from '../../state/appStore'
import { FACE_LABEL, spoolJoint, towerUrl, type TowerFace } from './towerLayout'

const SPOOL_COLOUR: Record<SpreadStatus, number> = {
  pass: 0x34b37a,
  partial: 0xf29a38,
  low: 0xe0565b,
  unscored: 0x9aa3ae,
}

const towers = new Map<string, Promise<THREE.Group>>()
function loadTower(url: string): Promise<THREE.Group> {
  if (!towers.has(url)) towers.set(url, new GLTFLoader().loadAsync(url).then((gltf) => gltf.scene))
  return towers.get(url)!
}

interface SpoolTag {
  pos: string
  joint: string
  motor: MotorSpread | undefined
  at: THREE.Vector3
}

type Side = 'left' | 'right'

function FaceRig({ side, face, byJoint }: { side: Side; face: TowerFace; byJoint: Record<string, MotorSpread> }) {
  const url = towerUrl(side)
  const [root, setRoot] = useState<THREE.Group | null>(null)
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const controls = useThree((s) => s.controls) as { target: THREE.Vector3; update: () => void } | null
  const invalidate = useThree((s) => s.invalidate)
  const sign = face === 'B' ? 1 : -1

  useEffect(() => {
    let alive = true
    loadTower(url).then((scene) => {
      if (!alive) return
      const clone = scene.clone(true)
      clone.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (mesh.isMesh) mesh.material = (mesh.material as THREE.MeshStandardMaterial).clone()
      })
      setRoot(clone)
    })
    return () => {
      alive = false
    }
  }, [url])

  useEffect(() => {
    if (!root || !controls) return
    // Frame the tower and most of the hand above it, so the palm or back reads at a glance.
    const box = new THREE.Box3()
    root.traverse((o) => {
      if ((o as THREE.Mesh).isMesh && !o.name.startsWith('hand')) box.expandByObject(o)
    })
    box.max.y += (box.max.y - box.min.y) * 1.6
    const centre = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    const vHalf = (camera.fov * Math.PI) / 360
    const hHalf = Math.atan(Math.tan(vHalf) * camera.aspect)
    const distance = Math.max(size.y / 2 / Math.tan(vHalf), size.x / 2 / Math.tan(hHalf)) * 1.25
    camera.position.set(centre.x, centre.y, centre.z + sign * distance)
    camera.near = distance / 50
    camera.far = distance * 10
    camera.updateProjectionMatrix()
    controls.target.copy(centre)
    controls.update()
    invalidate()
  }, [root, controls, camera, camera.aspect, sign, invalidate])

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
      material.emissiveIntensity = motor && motor.status !== 'pass' ? 0.45 : 0.15
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
          <div className={`gt-spool-tag ${tag.motor?.status ?? 'unscored'}`}>
            <span>
              <b>M{tag.motor?.motor ?? '?'}</b>{' '}
              {tag.motor?.fraction == null ? '—' : `${Math.round(tag.motor.fraction * 100)}%`}
            </span>
            <small>{tag.joint}</small>
          </div>
        </Html>
      ))}
    </>
  )
}

function FaceView({ side, face, byJoint }: { side: Side; face: TowerFace; byJoint: Record<string, MotorSpread> }) {
  const { scene } = usePalette()
  return (
    <div className="gt-tower-face">
      <div className="gt-tower-face-title">{FACE_LABEL[face]}</div>
      <Canvas
        frameloop="demand"
        dpr={[1, 2]}
        camera={{ fov: 30, position: [0, 0, 0.4], near: 0.01, far: 5 }}
        style={{ background: scene.bg }}
      >
        <hemisphereLight args={[scene.hemiSky, scene.hemiGround, scene.hemiIntensity]} />
        <directionalLight position={[0.2, 0.4, face === 'B' ? 0.6 : -0.6]} intensity={1.4} />
        <OrbitControls makeDefault enableDamping={false} />
        <FaceRig side={side} face={face} byJoint={byJoint} />
      </Canvas>
    </div>
  )
}

export function TowerPreview({ motors }: { motors: MotorSpread[] }) {
  const key = motors.map((m) => `${m.joint}:${m.status}:${m.fraction}`).join(',')
  const byJoint = useMemo(
    () => Object.fromEntries(motors.map((m) => [m.joint, m])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  )
  const side = useAppStore((s) => s.handInfo?.side) ?? 'right'
  return (
    <div className="gt-tower">
      <FaceView side={side} face="F" byJoint={byJoint} />
      <FaceView side={side} face="B" byJoint={byJoint} />
    </div>
  )
}

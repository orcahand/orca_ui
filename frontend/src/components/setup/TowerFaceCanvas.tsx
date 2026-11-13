// The live 3D tower one face of TowerPreview falls back to when the model has
// no rendered pictures. Kept apart so three.js loads only when it is drawn.

import { Canvas, useThree } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { SpreadStatus } from '../../api/types'
import { usePalette } from '../../theme/themeStore'
import { StudioLights } from '../three/StudioLights'
import type { Side, SpoolMark, TagStyle } from './TowerPreview'
import { spoolJoint, towerUrl, type TowerFace } from './towerLayout'

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
// How much of the wrist shows above the tower, in metres of model space.
const HAND_ABOVE_TOWER = 0.035

const towers = new Map<string, Promise<THREE.Group>>()
function loadTower(url: string): Promise<THREE.Group> {
  if (!towers.has(url)) towers.set(url, new GLTFLoader().loadAsync(url).then((gltf) => gltf.scene))
  return towers.get(url)!
}

interface SpoolTag {
  pos: string
  joint: string
  motor: SpoolMark | undefined
  at: THREE.Vector3
}

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

export function FaceCanvas({
  side,
  face,
  byJoint,
  tags,
}: {
  side: Side
  face: TowerFace
  byJoint: Record<string, SpoolMark>
  tags: TagStyle
}) {
  const { scene } = usePalette()
  return (
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
  )
}

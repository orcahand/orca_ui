// The calibration rig's digital twin in the dashboard's 3D view (docs/rig-dashboard.md):
// Shea's meshes (orca_files calibration_rig/twin/, rig frame mm, z up) in four groups —
// static, rotor Rz(plate), object (the tower) Rz(plate)·Rz(mounting), camera — and the
// tower's ChArUco tiles as textured quads at their seats. The live plate angle comes
// with /twin/state; HandScene mounts the hand with rigMountMatrix().

import { useThree } from '@react-three/fiber'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { twinFileUrl, twinTileUrl, type TwinInfo, type TwinState } from '../visual/api'

type Mat4 = number[][]
type Group = 'static' | 'rotor' | 'object' | 'camera'
interface Part { name: string; file: string; group: Group; color?: string; transform: Mat4 }

const TILE_MM = 78

/** Rig frame (mm, z up) to the scene (m, y up). */
export const RIG_TO_SCENE = new THREE.Matrix4()
  .makeRotationX(-Math.PI / 2)
  .multiply(new THREE.Matrix4().makeScale(0.001, 0.001, 0.001))

export const mat4 = (rows: Mat4) =>
  new THREE.Matrix4().set(...(rows.flat() as Parameters<THREE.Matrix4['set']>))

/** The hand URDF's matrix on the plate: scene ← rig ← hand (mm) ← URDF (m). */
export function rigMountMatrix(rigFromHand: Mat4): THREE.Matrix4 {
  return RIG_TO_SCENE.clone().multiply(mat4(rigFromHand)).multiply(new THREE.Matrix4().makeScale(1000, 1000, 1000))
}

function seatMatrix(seat: { corner: number[]; rpy: number[] }): THREE.Matrix4 {
  const [r, p, y] = seat.rpy.map((d) => (d * Math.PI) / 180)
  const m = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(r, p, y, 'ZYX'))
  m.setPosition(seat.corner[0], seat.corner[1], seat.corner[2])
  // The tile frame has x right, y down (image top at y = 0): the plane's +y is the image top.
  return m.multiply(new THREE.Matrix4().makeTranslation(TILE_MM / 2, TILE_MM / 2, 0))
    .multiply(new THREE.Matrix4().makeScale(1, -1, 1))
}

function fixed(o: THREE.Object3D, m?: THREE.Matrix4) {
  o.matrixAutoUpdate = false
  if (m) o.matrix.copy(m)
  o.matrixWorldNeedsUpdate = true
}

export function RigTwin({ twin, state, showTower }: { twin: TwinInfo; state: TwinState | null; showTower: boolean }) {
  const invalidate = useThree((s) => s.invalidate)
  const controls = useThree((s) => s.controls) as { target: THREE.Vector3; update: () => void } | null
  const camera = useThree((s) => s.camera)
  const groups = useMemo(() => {
    const root = new THREE.Group()
    fixed(root, RIG_TO_SCENE)
    const g = Object.fromEntries((['static', 'rotor', 'object', 'camera'] as Group[]).map((k) => {
      const grp = new THREE.Group()
      fixed(grp)
      root.add(grp)
      return [k, grp]
    })) as Record<Group, THREE.Group>
    return { root, ...g }
  }, [])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true
    const loader = new GLTFLoader()
    const disposables: { dispose: () => void }[] = []
    const parts = ((twin.parts as Part[]) ?? []).filter((p) => !p.name.startsWith('tile_') && twin.files.includes(p.file))
    Promise.all(parts.map(async (p) => {
      const gltf = await loader.loadAsync(twinFileUrl(p.file))
      const material = new THREE.MeshStandardMaterial({ color: p.color ?? '#999999', roughness: 0.7, metalness: 0.1 })
      disposables.push(material)
      gltf.scene.traverse((o) => {
        const mesh = o as THREE.Mesh
        if (mesh.isMesh) mesh.material = material
      })
      const holder = new THREE.Group()
      fixed(holder, mat4(p.transform))
      holder.add(gltf.scene)
      return { p, holder }
    })).then((list) => {
      if (!alive) return
      for (const { p, holder } of list) groups[p.group]?.add(holder)
      const textures = new THREE.TextureLoader()
      const plane = new THREE.PlaneGeometry(TILE_MM, TILE_MM)
      disposables.push(plane)
      for (const [name, seat] of Object.entries(twin.tile_seats ?? {})) {
        const tex = textures.load(twinTileUrl(name), () => invalidate())
        tex.colorSpace = THREE.SRGBColorSpace
        const material = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide })
        disposables.push(tex, material)
        const quad = new THREE.Mesh(plane, material)
        fixed(quad, seatMatrix(seat))
        groups.object.add(quad)
      }
      setLoaded(true)
      invalidate()
    }).catch((e) => console.error('rig twin load failed', e))
    return () => {
      alive = false
      for (const grp of [groups.static, groups.rotor, groups.object, groups.camera]) grp.clear()
      disposables.forEach((d) => d.dispose())
      setLoaded(false)
    }
  }, [twin, groups, invalidate])

  useEffect(() => {
    if (!state) return
    groups.rotor.matrix.copy(mat4(state.groups.rotor))
    groups.object.matrix.copy(mat4(state.groups.object_solved ?? state.groups.object_cad))
    groups.rotor.matrixWorldNeedsUpdate = groups.object.matrixWorldNeedsUpdate = true
    invalidate()
  }, [state, groups, invalidate])

  useEffect(() => {
    groups.object.visible = showTower
    invalidate()
  }, [showTower, groups, invalidate])

  // Frame the whole rig once it is there.
  useEffect(() => {
    if (!loaded || !controls) return
    groups.root.updateMatrixWorld(true)
    const sphere = new THREE.Box3().setFromObject(groups.root).getBoundingSphere(new THREE.Sphere())
    const persp = camera as THREE.PerspectiveCamera
    const distance = (sphere.radius / Math.tan((persp.fov * Math.PI) / 360)) * 1.05
    persp.position.copy(sphere.center).add(new THREE.Vector3(0.55, 0.45, 0.7).normalize().multiplyScalar(distance))
    persp.near = distance / 100
    persp.far = distance * 50
    persp.updateProjectionMatrix()
    controls.target.copy(sphere.center)
    controls.update()
    invalidate()
  }, [loaded, controls, camera, groups, invalidate])

  return <primitive object={groups.root} />
}

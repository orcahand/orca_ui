// The calibration rig's digital twin in the dashboard's 3D view (docs/rig-dashboard.md):
// Shea's meshes (orca_files calibration_rig/twin/, rig frame mm, z up) in four groups —
// static, rotor Rz(plate), object (the tower) Rz(plate)·Rz(mounting), camera — and the
// tower's ChArUco tiles as textured quads at their seats. Every enabled rig camera (A, B)
// is marked by its view frustum at its solved pose, or its CAD pose until 1b has solved it.
// The live plate angle comes with /twin/state; HandScene mounts the hand with rigMountMatrix().

import { useThree } from '@react-three/fiber'
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { twinFileUrl, twinTileUrl, type TwinInfo, type TwinState } from '../visual/api'

type Mat4 = number[][]
type Group = 'static' | 'rotor' | 'object' | 'camera'
interface Part { name: string; file: string; group: Group; color?: string; transform: Mat4 }

const TILE_MM = 78
const FRUSTUM_MM = { depth: 70, half: [39, 22] } // a 16:9 view, OpenCV camera frame (z forward)
const SOLVED = '#22c55e'
const CAD = '#f59e0b'

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

/** camera -> rig (OpenCV frame: x right, y down, z forward) looking from `eye` at `at`, rig z up. */
function lookAt(eye: number[], at: number[]): THREE.Matrix4 {
  const p = new THREE.Vector3(...eye)
  const z = new THREE.Vector3(...at).sub(p).normalize()
  const x = new THREE.Vector3().crossVectors(z, new THREE.Vector3(0, 0, 1)).normalize()
  const y = new THREE.Vector3().crossVectors(z, x)
  return new THREE.Matrix4().makeBasis(x, y, z).setPosition(p)
}

function frustum(color: string, label: string): THREE.Group {
  const { depth: d, half: [w, h] } = FRUSTUM_MM
  const c = [[-w, -h], [w, -h], [w, h], [-w, h]].map(([x, y]) => [x, y, d])
  const pts = c.flatMap((p, i) => [0, 0, 0, ...p, ...p, ...c[(i + 1) % 4]])
  pts.push(0, -h, d, 0, -h - 12, d) // a tick at the image top
  const geo = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
  const g = new THREE.Group()
  g.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color })))
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 64
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.fillStyle = color
    ctx.font = 'bold 48px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, 32, 34)
  }
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }))
  sprite.scale.setScalar(30)
  sprite.position.set(0, -h - 30, 0)
  g.add(sprite)
  return g
}

function disposeTree(o: THREE.Object3D) {
  o.traverse((x) => {
    const m = x as THREE.Mesh
    m.geometry?.dispose()
    const mat = m.material as THREE.Material & { map?: THREE.Texture }
    mat?.map?.dispose()
    mat?.dispose?.()
  })
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
  const cams = useMemo(() => {
    const g = new THREE.Group()
    fixed(g)
    groups.root.add(g)
    return g
  }, [groups])

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

  // The cameras' frustums, rebuilt only when a pose changes (the state comes at 5 Hz).
  const camKey = JSON.stringify(state?.cameras ?? null)
  useEffect(() => {
    const all = JSON.parse(camKey) as TwinState['cameras'] | null
    for (const [name, c] of Object.entries(all ?? {})) {
      if (!c?.enabled) continue
      const m = c.solved ? mat4(c.solved) : c.cad ? lookAt(c.cad.position, c.cad.look_at) : null
      if (!m) continue
      const f = frustum(c.solved ? SOLVED : CAD, name.toUpperCase())
      fixed(f, m)
      cams.add(f)
    }
    invalidate()
    return () => {
      cams.children.forEach(disposeTree)
      cams.clear()
    }
  }, [camKey, cams, invalidate])

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

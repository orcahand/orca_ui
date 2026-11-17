// The bench tower as drawn: frame parts plus one mesh per motor slot. The
// GLB comes from scripts/build_bench_tower.py, which keeps the STEP's
// component names; slot mNN is motor number NN.

import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

export const TOWER_URL = '/bench/tower.glb'

export interface TowerSlot {
  slot: number
  meshes: THREE.Mesh[]
  material: THREE.MeshStandardMaterial
  center: THREE.Vector3
  // Horizontal direction from the tower's axis to the slot: its label shows
  // only while this side faces the camera.
  outward: THREE.Vector3
}

export interface Tower {
  root: THREE.Group
  frame: THREE.MeshStandardMaterial
  slots: TowerSlot[]
  center: THREE.Vector3
  size: number
}

// GLTFLoader strips ':' from node names, so "m05:1" arrives as "m051".
const SLOT_NAME = /^m(\d{2})\d*$/

function slotOf(object: THREE.Object3D): number | null {
  for (let o: THREE.Object3D | null = object; o; o = o.parent) {
    const match = SLOT_NAME.exec(o.name)
    if (match) return parseInt(match[1], 10)
  }
  return null
}

let request: Promise<Tower> | null = null

export function loadTower(): Promise<Tower> {
  if (!request) {
    request = new GLTFLoader().loadAsync(TOWER_URL).then((gltf) => build(gltf.scene))
    request.catch(() => {
      request = null
    })
  }
  return request
}

function build(scene: THREE.Group): Tower {
  scene.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(scene)
  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3()).length()
  const frame = new THREE.MeshStandardMaterial({ roughness: 0.7, transparent: true, opacity: 0.55 })
  const bySlot = new Map<number, THREE.Mesh[]>()
  scene.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return
    const slot = slotOf(object)
    if (slot === null) {
      object.material = frame
      // The frame never takes the pointer, so a motor behind it stays clickable.
      object.raycast = () => undefined
      return
    }
    bySlot.set(slot, [...(bySlot.get(slot) ?? []), object])
  })
  const slots: TowerSlot[] = [...bySlot.entries()].map(([slot, meshes]) => {
    const material = new THREE.MeshStandardMaterial({ roughness: 0.45, metalness: 0.1 })
    const bounds = new THREE.Box3()
    for (const mesh of meshes) {
      mesh.material = material
      bounds.expandByObject(mesh)
    }
    const c = bounds.getCenter(new THREE.Vector3())
    const outward = new THREE.Vector3(c.x - center.x, 0, c.z - center.z)
    if (outward.lengthSq() > 1e-12) outward.normalize()
    return { slot, meshes, material, center: c, outward }
  })
  slots.sort((a, b) => a.slot - b.slot)
  return { root: scene, frame, slots, center, size }
}

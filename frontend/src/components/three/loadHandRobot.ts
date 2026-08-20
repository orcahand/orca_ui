// URDF loading: urdf-loader with a GLB mesh callback. Missing meshes get a
// small placeholder box so kinematics still animate.

import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import URDFLoader, { type URDFRobot } from 'urdf-loader'

export async function loadHandRobot(urdfUrl: string): Promise<URDFRobot> {
  const manager = new THREE.LoadingManager()
  const loader = new URDFLoader(manager)
  const gltf = new GLTFLoader(manager)

  // urdf-loader 0.13 calls loadMeshCb(path, manager, material, done) while
  // its stale .d.ts still declares three args — take the last arg as `done`
  // so both signatures work.
  loader.loadMeshCb = ((...args: unknown[]) => {
    const path = args[0] as string
    const done = args[args.length - 1] as (
      obj: THREE.Object3D | null,
      err?: Error,
    ) => void
    gltf.load(
      path,
      (result) => done(result.scene),
      undefined,
      () => {
        console.warn('mesh missing, using placeholder:', path)
        const box = new THREE.Mesh(
          new THREE.BoxGeometry(0.02, 0.02, 0.02),
          new THREE.MeshStandardMaterial({ color: 0x555b66 }),
        )
        done(box)
      },
    )
  }) as never

  // GLB meshes stream in through the manager after the URDF parses; wait for
  // them so callers (camera framing) see real geometry, not an empty box.
  const meshesLoaded = new Promise<void>((resolve) => {
    manager.onLoad = () => resolve()
  })
  const robot = await loader.loadAsync(urdfUrl)
  await Promise.race([
    meshesLoaded,
    new Promise((resolve) => setTimeout(resolve, 5000)),
  ])
  robot.rotation.x = -Math.PI / 2 // URDF Z-up -> three.js Y-up
  for (const joint of Object.values(robot.joints)) {
    // Clamp against orca_core ROMs upstream, not the URDF's CAD limits
    // (several joints' calibrated ROMs exceed them).
    joint.ignoreLimits = true
  }
  robot.traverse((object) => {
    object.frustumCulled = true
  })
  return robot
}

// The mesh bundle ships the white silicone skin (its own `#e8eaed` material,
// on the `*Skin` meshes — the forearm logo shares the material but not the
// name) and a separate dark plastic material on every structural mesh.
// Touch and full hands wear Paxini's black skin instead, so repaint rather
// than ship a second bundle — and the frame gets darkened too, or the stock
// `#212529` plastic reads as a mismatched grey next to true-black silicone.
const SKIN_MESH = /skin/i

// Linear, not sRGB: the bundle's baseColorFactors were written as if they
// were already linear, so the printed frame's "#212529" lands at 0.129 linear.
// A normal sRGB black here would read as a hole next to it; skin and frame
// sit a little apart so the silicone still separates from the plastic even
// with both dark.
const BLACK_SKIN: [r: number, g: number, b: number] = [0.06, 0.062, 0.068]
const BLACK_FRAME: [r: number, g: number, b: number] = [0.1, 0.104, 0.115]

/**
 * The material makeGhost created for each ghost. Kept off to the side for the
 * same reason as skinMaterials: Object3D.clone() deep-copies userData through
 * JSON, so a material stashed there would not survive a clone.
 */
const ghostMaterials = new WeakMap<THREE.Object3D, THREE.MeshStandardMaterial>()

export type SkinTone = 'white' | 'black'

/**
 * Marks an object (and its subtree) as an overlay rather than hand geometry.
 *
 * The force-arrow and joint-glow layers parent themselves to the robot's
 * links so they inherit the kinematics — which also puts them in reach of
 * robot.traverse(). setSkinTone was repainting them as black plastic: the
 * arrows kept their instanceColor but had material.color driven to
 * BLACK_FRAME, so every arrow rendered at a tenth of its intended
 * brightness, and the glow rings had their material swapped outright, which
 * silently disconnected the error ramp JointGlowLayer was still writing to
 * the original. Only the resultant arrow escaped, because ArrowHelper
 * re-sets material.color on every frame.
 */
export function markOverlay(object: THREE.Object3D): void {
  object.userData.orcaOverlay = true
}

/** Walks the hand's own meshes, stopping at any overlay subtree. */
function eachHandMesh(
  root: THREE.Object3D,
  visit: (mesh: THREE.Mesh) => void,
): void {
  if (root.userData.orcaOverlay) return
  const mesh = root as THREE.Mesh
  if (mesh.isMesh) visit(mesh)
  for (const child of root.children) eachHandMesh(child, visit)
}

// Both materials per mesh, so toggling back and forth doesn't clone a new
// one each time. Off to the side rather than in mesh.userData, which
// Object3D.clone() deep-copies through JSON — makeGhost would serialize the
// materials stashed there.
const skinMaterials = new WeakMap<
  THREE.Mesh,
  { white: THREE.Material; black: THREE.Material }
>()

export function setSkinTone(robot: THREE.Object3D, tone: SkinTone): void {
  eachHandMesh(robot, (mesh) => {
    let pair = skinMaterials.get(mesh)
    if (!pair) {
      const isSkin = SKIN_MESH.test(mesh.name)
      const white = mesh.material as THREE.MeshStandardMaterial
      // Clone rather than recolor in place: the loader is free to hand the
      // same material to more than one mesh. 'white' keeps the stock
      // material untouched for both skin and frame — only 'black' repaints.
      const black = white.clone()
      black.color.setRGB(
        ...(isSkin ? BLACK_SKIN : BLACK_FRAME),
        THREE.LinearSRGBColorSpace,
      )
      if (isSkin) {
        black.roughness = 0.85 // matte silicone, against the frame's stock sheen
        black.metalness = 0
      }
      pair = { white, black }
      skinMaterials.set(mesh, pair)
    }
    mesh.material = pair[tone]
  })
}

/** Exactly the shape the palette stores per theme for each ghost. */
export interface GhostAppearance {
  color: number
  opacity: number
  emissiveIntensity: number
}

export interface GhostOptions extends Partial<GhostAppearance> {
  // Link names whose meshes are dropped from the ghost (static links like
  // the tower would just z-fight with the solid hand's identical geometry).
  hideLinks?: string[]
}

export function makeGhost(
  robot: URDFRobot,
  {
    color = 0x7f8ea2,
    opacity = 0.22,
    emissiveIntensity = 0,
    hideLinks = [],
  }: GhostOptions = {},
): URDFRobot | null {
  const ghost = robot.clone(true) as URDFRobot
  // URDFRobot.clone rebuilds the joint map; verify before trusting it.
  if (!ghost.joints || Object.keys(ghost.joints).length !== Object.keys(robot.joints).length) {
    console.warn('URDFRobot.clone did not preserve joints; ghost disabled')
    return null
  }
  const material = new THREE.MeshStandardMaterial({
    color,
    // Self-lit ghosts (teleop) stay recognizably colored from any angle
    // instead of washing out to gray under the scene lights.
    emissive: emissiveIntensity > 0 ? color : 0x000000,
    emissiveIntensity,
    transparent: true,
    opacity,
    depthWrite: false,
    side: THREE.FrontSide,
    // Pull the ghost toward the camera in the depth test: when it exactly
    // coincides with the solid hand the coplanar surfaces would otherwise
    // z-fight and flicker.
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  })
  const hidden = new Set(hideLinks)
  ghost.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (!mesh.isMesh) return
    // Every ghost mesh takes the ghost material, hidden ones included.
    // Object3D.clone() copies material by *reference*, so a mesh skipped here
    // would keep pointing at the real hand's material — and anything that
    // then edited "the ghost's" materials would be editing the hand's.
    mesh.material = material
    mesh.renderOrder = 10
    if (hidden.size > 0 && hidden.has(owningLinkName(mesh))) {
      mesh.visible = false
    }
  })
  ghostMaterials.set(ghost, material)
  return ghost
}

/**
 * Re-tint an existing ghost in place, for a theme change. A pale slate ghost
 * reads against a dark viewport and disappears against paper — and vanishing
 * exactly where it leaves the hand defeats the point of drawing it, since
 * the deviation is the whole signal.
 *
 * makeGhost gives every mesh the same material instance, so the Set is
 * really a formality — it just keeps this honest if that ever stops being
 * true.
 */
export function setGhostAppearance(
  ghost: THREE.Object3D,
  { color, opacity, emissiveIntensity }: GhostAppearance,
): void {
  // Edits the one material makeGhost built, looked up by identity rather
  // than found by walking the ghost. Traversing repainted whatever material
  // each mesh happened to hold, which on a hand whose skin is left as the
  // stock white — i.e. any hand without tactile sensors — reached straight
  // through the clone into the real hand and turned its forearm and tower
  // into translucent accent-coloured ghosts.
  const material = ghostMaterials.get(ghost)
  if (!material) return
  material.color.set(color)
  material.opacity = opacity
  material.emissive.set(emissiveIntensity > 0 ? color : 0x000000)
  material.emissiveIntensity = emissiveIntensity
}

// Nearest URDF link up the parent chain — links nest through joints, so a
// mesh's owning link is the first ancestor flagged isURDFLink.
function owningLinkName(mesh: THREE.Object3D): string {
  let node: THREE.Object3D | null = mesh
  while (node) {
    if ((node as unknown as { isURDFLink?: boolean }).isURDFLink) {
      return node.name
    }
    node = node.parent
  }
  return ''
}

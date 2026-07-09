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

export interface GhostOptions {
  color?: number
  opacity?: number
  emissiveIntensity?: number
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
    if (hidden.size > 0 && hidden.has(owningLinkName(mesh))) {
      mesh.visible = false
      return
    }
    mesh.material = material
    mesh.renderOrder = 10
  })
  return ghost
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

// URDF loading: urdf-loader with a GLB mesh callback. Missing meshes get a
// small placeholder box so kinematics still animate.

import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import URDFLoader, { type URDFRobot } from 'urdf-loader'

export async function loadHandRobot(urdfUrl: string): Promise<URDFRobot> {
  const manager = new THREE.LoadingManager()
  const loader = new URDFLoader(manager)
  const gltf = new GLTFLoader(manager)

  loader.loadMeshCb = (path, _manager, done) => {
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
  }

  const robot = await loader.loadAsync(urdfUrl)
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

export function makeGhost(robot: URDFRobot): URDFRobot | null {
  const ghost = robot.clone(true) as URDFRobot
  // URDFRobot.clone rebuilds the joint map; verify before trusting it.
  if (!ghost.joints || Object.keys(ghost.joints).length !== Object.keys(robot.joints).length) {
    console.warn('URDFRobot.clone did not preserve joints; ghost disabled')
    return null
  }
  const material = new THREE.MeshStandardMaterial({
    color: 0x7f8ea2,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
    side: THREE.FrontSide,
  })
  ghost.traverse((object) => {
    const mesh = object as THREE.Mesh
    if (mesh.isMesh) {
      mesh.material = material
      mesh.renderOrder = 10
    }
  })
  return ghost
}

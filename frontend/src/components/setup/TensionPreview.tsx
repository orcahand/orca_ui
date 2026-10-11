// The guided-tensioning hand preview: a scripted pose rather than the live
// stream. "pose" holds the current stage's pose (other fingers parked out of
// the way), "sweep" keeps that pose and walks the stage's joints one at a
// time through their full ROM, and "still" shows the mid-ROM hand.
// Joints still to tension are tinted red/orange and passed ones a light green;
// the sweep skips passed joints.

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { JointInfo, SpreadStatus } from '../../api/types'
import { usePalette } from '../../theme/themeStore'
import { FRONT_VIEW, standUpright } from '../three/frontView'
import { loadHandRobot, owningLinkName, setSkinTone } from '../three/loadHandRobot'
import { fingerOf, stagePose, thumbOut, towardThumb, type TowardThumb } from './stagePoses'

export type PreviewMode = 'pose' | 'sweep' | 'still'
export interface PreviewStage {
  key: string
  joints: string[]
}

const FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky'] as const
const JOINT_PERIOD_S = 2.4
const TINT: Partial<Record<SpreadStatus, number>> = { low: 0xe0565b, partial: 0xf29a38, pass: 0x34b37a }
const DEG2RAD = Math.PI / 180
const STATIC_LINKS = new Set(['tower', 'forearm'])

// Frame the fingers and palm, not the tower the hand is mounted on.
function handBounds(robot: URDFRobot): THREE.Sphere {
  const box = new THREE.Box3()
  robot.traverse((object) => {
    if ((object as THREE.Mesh).isMesh && !STATIC_LINKS.has(owningLinkName(object))) {
      box.expandByObject(object)
    }
  })
  if (box.isEmpty()) box.setFromObject(robot)
  return box.getBoundingSphere(new THREE.Sphere())
}

const tintCache = new WeakMap<THREE.Material, Map<number, THREE.Material>>()

// A passed joint keeps most of its skin colour, so it reads as done rather than as a warning.
function tinted(base: THREE.MeshStandardMaterial, color: number, light: boolean): THREE.Material {
  let byColor = tintCache.get(base)
  if (!byColor) tintCache.set(base, (byColor = new Map()))
  let material = byColor.get(color)
  if (!material) {
    const clone = base.clone()
    if (light) clone.color.lerp(new THREE.Color(color), 0.45)
    else clone.color.setHex(color)
    clone.emissive = new THREE.Color(color)
    clone.emissiveIntensity = light ? 0.12 : 0.35
    byColor.set(color, (material = clone))
  }
  return material
}

function linkMeshes(joint: THREE.Object3D): THREE.Mesh[] {
  const meshes: THREE.Mesh[] = []
  const walk = (object: THREE.Object3D) => {
    if ((object as { isURDFJoint?: boolean }).isURDFJoint && object !== joint) return
    if ((object as THREE.Mesh).isMesh) meshes.push(object as THREE.Mesh)
    object.children.forEach(walk)
  }
  walk(joint)
  return meshes
}

// Call right after setSkinTone, which resets every mesh to its untinted material.
function applyTints(robot: URDFRobot, statuses: Record<string, SpreadStatus>) {
  for (const [name, joint] of Object.entries(robot.joints)) {
    const status = statuses[name]
    const color = TINT[status]
    for (const mesh of linkMeshes(joint)) {
      if (color !== undefined) mesh.material = tinted(mesh.material as THREE.MeshStandardMaterial, color, status === 'pass')
    }
  }
}

function centre(joint: JointInfo): number {
  return joint.id === 'wrist' ? joint.neutral : (joint.rom[0] + joint.rom[1]) / 2
}

// Held pose → upper end → lower end → held pose, eased, as u runs 0 → 1, so
// each joint starts and ends where the stage pose holds it.
function sweep(held: number, rom: [number, number], u: number): number {
  const ease = (a: number, b: number, f: number) => a + ((b - a) * (1 - Math.cos(f * Math.PI))) / 2
  if (u < 0.25) return ease(held, rom[1], u / 0.25)
  if (u < 0.75) return ease(rom[1], rom[0], (u - 0.25) / 0.5)
  return ease(rom[0], held, (u - 0.75) / 0.25)
}

function PreviewRig({
  urdfUrl,
  joints,
  mode,
  stage,
  statuses,
  blackSkin,
  onJoint,
}: {
  urdfUrl: string
  joints: JointInfo[]
  mode: PreviewMode
  stage?: PreviewStage | null
  statuses: Record<string, SpreadStatus>
  blackSkin: boolean
  onJoint: (joint: string | null) => void
}) {
  const [robot, setRobot] = useState<URDFRobot | null>(null)
  const [toward, setToward] = useState<TowardThumb>({})
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const controls = useThree((s) => s.controls) as { target: THREE.Vector3; update: () => void } | null
  const sweeping = useRef<string | null>(null)

  useEffect(() => {
    let disposed = false
    loadHandRobot(urdfUrl).then((loaded) => {
      if (disposed) return
      standUpright(loaded, joints)
      setToward({ ...towardThumb(loaded, joints), ...thumbOut(loaded, joints) })
      setRobot(loaded)
    })
    return () => {
      disposed = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urdfUrl])

  useEffect(() => {
    if (!robot) return
    setSkinTone(robot, blackSkin ? 'black' : 'white')
    applyTints(robot, statuses)
  }, [robot, blackSkin, statuses])

  useEffect(() => {
    if (!robot || !controls) return
    for (const joint of joints) robot.joints[joint.id]?.setJointValue(centre(joint) * DEG2RAD)
    robot.updateMatrixWorld(true)
    const sphere = handBounds(robot)
    const distance = (sphere.radius / Math.tan((camera.fov * DEG2RAD) / 2)) * 1.1
    camera.position.copy(sphere.center).addScaledVector(FRONT_VIEW, distance)
    camera.near = distance / 100
    camera.far = distance * 50
    camera.updateProjectionMatrix()
    controls.target.copy(sphere.center)
    controls.update()
  }, [robot, controls, camera, joints])

  const pose = useMemo(
    () => stagePose(mode === 'still' ? null : (stage?.key ?? null), joints, toward),
    [mode, stage?.key, joints, toward],
  )
  const sweepJoints = useMemo(() => {
    const known = new Set(joints.map((j) => j.id))
    const ids = stage
      ? stage.joints.filter((id) => known.has(id))
      : FINGERS.flatMap((f) => joints.filter((j) => fingerOf(j.id) === f).map((j) => j.id))
    return ids.filter((id) => statuses[id] !== 'pass')
  }, [stage, joints, statuses])

  useFrame(({ clock }) => {
    if (!robot) return
    const t = clock.getElapsedTime()
    const active =
      mode === 'sweep' && sweepJoints.length
        ? sweepJoints[Math.floor(t / JOINT_PERIOD_S) % sweepJoints.length]
        : null
    if (active !== sweeping.current) {
      sweeping.current = active
      onJoint(active)
    }
    const u = (t % JOINT_PERIOD_S) / JOINT_PERIOD_S
    for (const joint of joints) {
      let deg = pose[joint.id] ?? centre(joint)
      if (joint.id === active) deg = sweep(deg, joint.rom, u)
      robot.joints[joint.id]?.setJointValue(deg * DEG2RAD)
    }
  })

  return robot ? <primitive object={robot} /> : null
}

export function TensionPreview(props: {
  urdfUrl: string
  joints: JointInfo[]
  mode: PreviewMode
  stage?: PreviewStage | null
  statuses: Record<string, SpreadStatus>
  blackSkin: boolean
}) {
  const { scene } = usePalette()
  const [joint, setJoint] = useState<string | null>(null)
  return (
    <div className="gt-preview">
      <Canvas
        dpr={[1, 2]}
        camera={{ fov: 35, position: [0.28, 0.25, 0.3], near: 0.01, far: 10 }}
        style={{ background: scene.bg }}
      >
        <hemisphereLight args={[scene.hemiSky, scene.hemiGround, scene.hemiIntensity]} />
        <directionalLight position={[0.4, 0.8, 0.6]} intensity={1.6} />
        <directionalLight position={[-0.5, 0.3, -0.4]} intensity={0.6} />
        <OrbitControls makeDefault enableDamping={false} />
        <PreviewRig {...props} onJoint={setJoint} />
      </Canvas>
      {props.mode === 'sweep' && joint && (
        <div className="gt-preview-caption"><b>{joint.replace('_', ' ')}</b> · full range</div>
      )}
    </div>
  )
}

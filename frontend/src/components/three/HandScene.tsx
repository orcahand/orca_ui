// The 3D hand scene: solid hand posed from the measured joints (commanded /
// estimate fallback), optional translucent ghost from the naive motor
// estimate, joint-glow rings, and fingertip force arrows. Renders on demand;
// stream data invalidates the frame.

import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Grid } from '@react-three/drei'
import { useEffect, useState } from 'react'
import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { FingertipEntry, SensorMounts } from '../../api/rest'
import type {
  Capabilities,
  JointCalibrationEntry,
  JointInfo,
  ModelMetadata,
  TaxelGeometry,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'
import { subscribeFrames } from '../../state/streamStore'
import { ForceArrowLayer } from './ForceArrowLayer'
import { JointGlowLayer } from './JointGlowLayer'
import { JointPoseAdapter } from './JointPoseAdapter'
import { loadHandRobot, makeGhost } from './loadHandRobot'

export interface HandAssets {
  metadata: ModelMetadata
  calibration: Record<string, JointCalibrationEntry>
  fingertips: Record<string, FingertipEntry>
  sensorMounts: SensorMounts | null // null: no tactile kinematics available
  taxelGeometry: TaxelGeometry | null
}

interface Rig {
  robot: URDFRobot
  ghost: URDFRobot | null
  // Accent-colored second ghost posed from the raw teleop retargeter output
  // (teleop.targets) — during an engaged ramp it visibly leads the hand.
  teleopGhost: URDFRobot | null
  adapter: JointPoseAdapter
  ghostAdapter: JointPoseAdapter | null
  teleopGhostAdapter: JointPoseAdapter | null
  glow: JointGlowLayer
  arrows: ForceArrowLayer
  // Measured from the bare robot BEFORE overlay layers attach: the arrow
  // layer's unit-height instanced geometry would otherwise inflate the box
  // (Box3.setFromObject ignores per-instance matrices).
  bounds: THREE.Sphere
}

function HandRig({
  assets,
  joints,
  caps,
}: {
  assets: HandAssets
  joints: JointInfo[]
  caps: Capabilities
}) {
  const invalidate = useThree((s) => s.invalidate)
  const controls = useThree((s) => s.controls) as { target: THREE.Vector3; update: () => void } | null
  const [rig, setRig] = useState<Rig | null>(null)

  useEffect(() => {
    let disposed = false
    let built: Rig | null = null
    loadHandRobot(assets.metadata.urdf_url)
      .then((robot) => {
        if (disposed) {
          return
        }
        robot.updateMatrixWorld(true)
        const bounds = new THREE.Box3()
          .setFromObject(robot)
          .getBoundingSphere(new THREE.Sphere())
        const ghost = makeGhost(robot)
        // Emissive cyan so it can't be confused with the gray motor ghost;
        // the static tower/forearm never move, so ghosting them adds nothing.
        const teleopGhost = makeGhost(robot, {
          color: 0x22d3ee,
          opacity: 0.45,
          emissiveIntensity: 0.6,
          hideLinks: ['tower', 'forearm'],
        })
        built = {
          robot,
          ghost,
          teleopGhost,
          adapter: new JointPoseAdapter(robot, assets.calibration, joints),
          ghostAdapter: ghost
            ? new JointPoseAdapter(ghost, assets.calibration, joints)
            : null,
          teleopGhostAdapter: teleopGhost
            ? new JointPoseAdapter(teleopGhost, assets.calibration, joints)
            : null,
          glow: new JointGlowLayer(robot),
          arrows: new ForceArrowLayer(
            robot, assets.fingertips, assets.sensorMounts, assets.taxelGeometry),
          bounds,
        }
        setRig(built)
      })
      .catch((error) => {
        console.error('URDF load failed', error)
        useAppStore.getState().setError(`3D model load failed: ${error}`)
      })
    return () => {
      disposed = true
      if (built) {
        built.glow.dispose()
        built.arrows.dispose()
      }
      setRig(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets.metadata.urdf_url])

  // Live calibration updates (the YAML-tuning loop).
  useEffect(() => {
    rig?.adapter.setCalibration(assets.calibration)
    rig?.ghostAdapter?.setCalibration(assets.calibration)
    rig?.teleopGhostAdapter?.setCalibration(assets.calibration)
    invalidate()
  }, [assets.calibration, rig, invalidate])

  // Frame the camera on the hand once it exists: fit the whole model with a
  // margin, looking down from a 3/4 angle.
  const camera = useThree((s) => s.camera)
  useEffect(() => {
    if (!rig || !controls) return
    const sphere = rig.bounds
    const persp = camera as THREE.PerspectiveCamera
    const fovRad = (persp.fov * Math.PI) / 180
    const distance = (sphere.radius / Math.tan(fovRad / 2)) * 1.15
    // View from the thumb's side of the hand (so the thumb is never hidden
    // behind the palm), nudged toward the fingertips for a 3/4 look, from
    // ~40° above. Derived from the model, so left hands frame correctly too.
    const worldPos = new THREE.Vector3()
    const direction = new THREE.Vector3(1, 0, 1)
    const thumbLink = rig.robot.links['thumb_fingertip']
    if (thumbLink) {
      thumbLink.getWorldPosition(worldPos)
      direction.copy(worldPos).sub(sphere.center)
      direction.y = 0
      if (direction.lengthSq() > 1e-8) direction.normalize()
      else direction.set(1, 0, 1).normalize()
    }
    const middleLink = rig.robot.links['middle_fingertip']
    if (middleLink) {
      middleLink.getWorldPosition(worldPos)
      const toward = worldPos.sub(sphere.center)
      toward.y = 0
      if (toward.lengthSq() > 1e-8) {
        direction.addScaledVector(toward.normalize(), 0.45)
      }
    }
    direction.normalize().y = 0.8
    direction.normalize()
    persp.position.copy(sphere.center).addScaledVector(direction, distance)
    persp.near = distance / 100
    persp.far = distance * 50
    persp.updateProjectionMatrix()
    controls.target.copy(sphere.center)
    controls.update()
    invalidate()
  }, [rig, controls, camera, invalidate])

  // Pose + overlay updates from the stream (outside React).
  useEffect(() => {
    if (!rig) return
    return subscribeFrames((frames) => {
      const scene = useAppStore.getState().scene
      // Layered per-joint knowledge: the motor estimate covers every joint,
      // encoder measurements override where they exist (all 17 slots on a
      // sensing hand — a joint missing its encoder calibration falls back to
      // the estimate). Non-encoder hands: commanded targets win instead.
      rig.adapter.apply(frames.joints.estimate)
      if (caps.encoders) {
        rig.adapter.apply(frames.joints.measured)
      } else {
        rig.adapter.apply(frames.joints.target)
      }

      if (rig.ghost) {
        // Without encoders the main hand already shows the motor estimate,
        // so the ghost would just duplicate it — needs both to mean anything.
        const showGhost = scene.ghost && caps.motors && caps.encoders
        rig.ghost.visible = showGhost
        if (showGhost) rig.ghostAdapter?.apply(frames.joints.estimate)
      }

      if (rig.teleopGhost) {
        // Self-hides when no teleop session streams targets; the adapter
        // ROM-clamps + calibrates identically to every other stream.
        const showTeleop =
          scene.teleopGhost &&
          isTeleopActive(useTeleopStore.getState().session) &&
          Object.keys(frames.joints.teleopTarget).length > 0
        rig.teleopGhost.visible = showTeleop
        if (showTeleop) {
          rig.teleopGhostAdapter?.apply(frames.joints.teleopTarget)
        }
      }

      rig.glow.setVisible(scene.jointGlow && caps.encoders)
      if (scene.jointGlow && caps.encoders) {
        rig.glow.update(
          frames.joints.measured,
          frames.joints.target,
          performance.now(),
        )
      }

      const tactileOk = caps.tactile && rig.arrows.available
      const scheme = useAppStore.getState().tactile.colorScheme
      rig.arrows.setResultantVisible(scene.forceResultant && tactileOk)
      rig.arrows.setTaxelsVisible(scene.forceTaxels && tactileOk)
      if (scene.forceResultant && tactileOk) {
        rig.arrows.updateResultants(frames.tactile.forces, scheme)
      }
      if (scene.forceTaxels && tactileOk) {
        rig.arrows.updateTaxels(frames.tactile.taxels, scheme)
      }
      invalidate()
    })
  }, [rig, caps, invalidate])

  if (!rig) return null
  return (
    <>
      <primitive object={rig.robot} />
      {rig.ghost && <primitive object={rig.ghost} />}
      {rig.teleopGhost && <primitive object={rig.teleopGhost} />}
    </>
  )
}

export function HandScene({
  assets,
  joints,
  caps,
}: {
  assets: HandAssets
  joints: JointInfo[]
  caps: Capabilities
}) {
  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 2]}
      camera={{ fov: 35, position: [0.28, 0.25, 0.3], near: 0.01, far: 10 }}
      style={{ background: '#14161f', minHeight: 480 }}
    >
      <hemisphereLight args={['#cfd6e4', '#20222e', 0.9]} />
      <directionalLight position={[0.5, 1, 0.6]} intensity={1.4} />
      <directionalLight position={[-0.6, 0.4, -0.5]} intensity={0.35} />
      <Grid
        position={[0, -0.001, 0]}
        args={[1.2, 1.2]}
        cellSize={0.025}
        cellColor="#2a2e3e"
        sectionSize={0.1}
        sectionColor="#3a4054"
        fadeDistance={0.9}
        infiniteGrid
      />
      <OrbitControls makeDefault enableDamping={false} />
      <HandRig assets={assets} joints={joints} caps={caps} />
    </Canvas>
  )
}

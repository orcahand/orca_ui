// Emissive rings at the revolute joint frames, encoding tracking error
// (|measured − target|): invisible below a 1° dead-band, ramping dim-blue →
// amber → red toward 15°. Falls back to encoding measured joint speed when
// no target stream exists.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'

const DEAD_BAND_DEG = 1
const SATURATE_DEG = 15
const RING_RADIUS = 0.007
const RING_TUBE = 0.0011

const COLOR_LOW = new THREE.Color('#7f8ea2')
const COLOR_MID = new THREE.Color('#f59e0b')
const COLOR_HIGH = new THREE.Color('#ef4444')

interface GlowEntry {
  mesh: THREE.Mesh
  material: THREE.MeshBasicMaterial
  lastMeasured: number
  lastT: number
}

export class JointGlowLayer {
  private entries = new Map<string, GlowEntry>()
  private geometry = new THREE.TorusGeometry(RING_RADIUS, RING_TUBE, 8, 24)

  constructor(robot: URDFRobot) {
    const zAxis = new THREE.Vector3(0, 0, 1)
    for (const [name, joint] of Object.entries(robot.joints)) {
      if (joint.jointType !== 'revolute' && joint.jointType !== 'continuous') {
        continue
      }
      const material = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        color: COLOR_LOW,
      })
      const mesh = new THREE.Mesh(this.geometry, material)
      // Torus lies in XY (normal +Z); align the normal with the joint axis.
      const axis = new THREE.Vector3().copy(joint.axis as THREE.Vector3).normalize()
      mesh.quaternion.setFromUnitVectors(zAxis, axis)
      mesh.renderOrder = 20
      joint.add(mesh)
      this.entries.set(name, { mesh, material, lastMeasured: NaN, lastT: 0 })
    }
  }

  update(
    measured: Record<string, number>,
    target: Record<string, number>,
    nowMs: number,
  ): void {
    for (const [joint, entry] of this.entries) {
      const measuredDeg = measured[joint]
      if (measuredDeg === undefined) {
        entry.material.opacity = 0
        continue
      }
      let errorDeg: number
      if (target[joint] !== undefined) {
        errorDeg = Math.abs(measuredDeg - target[joint])
      } else {
        // Velocity fallback: deg change per 100 ms window.
        const dt = nowMs - entry.lastT
        errorDeg =
          dt > 0 && Number.isFinite(entry.lastMeasured)
            ? (Math.abs(measuredDeg - entry.lastMeasured) / dt) * 100
            : 0
        entry.lastMeasured = measuredDeg
        entry.lastT = nowMs
      }
      if (errorDeg < DEAD_BAND_DEG) {
        entry.material.opacity = 0
        continue
      }
      const t = Math.min((errorDeg - DEAD_BAND_DEG) / (SATURATE_DEG - DEAD_BAND_DEG), 1)
      entry.material.opacity = 0.25 + 0.75 * t
      if (t < 0.5) {
        entry.material.color.lerpColors(COLOR_LOW, COLOR_MID, t * 2)
      } else {
        entry.material.color.lerpColors(COLOR_MID, COLOR_HIGH, (t - 0.5) * 2)
      }
    }
  }

  setVisible(visible: boolean): void {
    for (const entry of this.entries.values()) entry.mesh.visible = visible
  }

  dispose(): void {
    for (const entry of this.entries.values()) {
      entry.mesh.removeFromParent()
      entry.material.dispose()
    }
    this.geometry.dispose()
    this.entries.clear()
  }
}

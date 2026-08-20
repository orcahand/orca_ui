// X-ray rings at the revolute joint frames, encoding tracking error
// (|measured − target|). At rest they sit as faint markers on the joint
// axes; error ramps them dim-blue → amber → red toward saturation. Rendered
// without depth testing so they read through the hand meshes (the joints sit
// inside the fingers). Falls back to encoding measured joint speed when no
// target stream exists (torque off).
//
// The rings are the one overlay whose *blending* is theme-dependent, not
// just its colors. Additive blending can only ever brighten what is behind
// it, so on paper — already near maximum — the rings simply vanish, and a
// saturated red at full error washes out to pale yellow instead of shouting.
// Light mode therefore blends normally, and lifts the resting opacity to
// compensate: normal blending at 0.14 over the hand's black plastic, which
// is what these rings mostly sit on top of, would show nothing at all.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import { palette } from '../../theme/palette'
import type { Palette } from '../../theme/palette'

const DEAD_BAND_DEG = 0.5
const SATURATE_DEG = 10
const RING_RADIUS = 0.0095
const RING_TUBE = 0.0012

const BLENDING: Record<Palette['scene']['glow']['blending'], THREE.Blending> = {
  additive: THREE.AdditiveBlending,
  normal: THREE.NormalBlending,
}

interface GlowEntry {
  mesh: THREE.Mesh
  material: THREE.MeshBasicMaterial
  lastMeasured: number
  lastT: number
}

export class JointGlowLayer {
  private entries = new Map<string, GlowEntry>()
  private geometry = new THREE.TorusGeometry(RING_RADIUS, RING_TUBE, 8, 24)
  // Parsed once per theme rather than per joint per frame; `glow` doubles as
  // the identity check, since palette() hands back a stable object.
  private glow: Palette['scene']['glow'] | null = null
  private low = new THREE.Color()
  private mid = new THREE.Color()
  private high = new THREE.Color()

  constructor(robot: URDFRobot) {
    this.syncTheme()
    const zAxis = new THREE.Vector3(0, 0, 1)
    for (const [name, joint] of Object.entries(robot.joints)) {
      if (joint.jointType !== 'revolute' && joint.jointType !== 'continuous') {
        continue
      }
      const material = new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: this.glow!.idleOpacity,
        blending: BLENDING[this.glow!.blending],
        depthWrite: false,
        depthTest: false, // joints sit inside the meshes; render through
        color: this.low,
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

  /**
   * Re-reads the active palette if it changed, re-parsing the ramp colors and
   * pushing the blending mode onto every ring material. Called from update()
   * so a theme switch lands on the next frame with no plumbing from React.
   */
  private syncTheme(): void {
    const glow = palette().scene.glow
    if (glow === this.glow) return
    this.glow = glow
    this.low.set(glow.low)
    this.mid.set(glow.mid)
    this.high.set(glow.high)
    const blending = BLENDING[glow.blending]
    for (const entry of this.entries.values()) {
      entry.material.blending = blending
      entry.material.needsUpdate = true // blending is a shader-program key
    }
  }

  update(
    measured: Record<string, number>,
    target: Record<string, number>,
    nowMs: number,
  ): void {
    this.syncTheme()
    const idleOpacity = this.glow!.idleOpacity
    for (const [joint, entry] of this.entries) {
      const measuredDeg = measured[joint]
      if (measuredDeg === undefined) {
        entry.material.opacity = idleOpacity
        entry.material.color.copy(this.low)
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
        entry.material.opacity = idleOpacity
        entry.material.color.copy(this.low)
        continue
      }
      const t = Math.min((errorDeg - DEAD_BAND_DEG) / (SATURATE_DEG - DEAD_BAND_DEG), 1)
      entry.material.opacity = 0.35 + 0.65 * t
      if (t < 0.5) {
        entry.material.color.lerpColors(this.low, this.mid, t * 2)
      } else {
        entry.material.color.lerpColors(this.mid, this.high, (t - 0.5) * 2)
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

// Tactile force arrows in the real sensor frames.
//
// Per finger, a "sensor group" is attached to the distal URDF link at the
// mesh-registered mount pose (T_fingertip_sensor from orca_core's kinematics
// data), so everything drawn inside it lives in the sensor frame — the frame
// both the taxel positions and the streamed forces are expressed in. The
// URDF kinematics then carries the arrows with the finger for free.
//
// Two independently toggleable layers:
//   resultant — one arrow per finger at the taxel centroid
//   taxels    — instanced shaft+head arrows, one per taxel

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { Finger, TaxelGeometry, Vec3 } from '../../api/types'
import type { FingertipEntry, SensorMounts } from '../../api/rest'
import type { ArrowColorScheme } from '../../state/appStore'
import { MAX_FORCE_SCALE, maxTaxelForce } from '../../theme/tokens'
import { getArrowColor2D } from '../tactile/taxelRender'

// Noise floors below which an arrow is meaningless. The toolbar threshold,
// when enabled, raises these rather than replacing them, so the 3D view hides
// exactly what the 2D taxel maps hide.
const RESULTANT_MIN_N = 0.3
const RESULTANT_MAX_LEN_M = 0.035
const TAXEL_MIN_N = 0.3
const TAXEL_BASE_LEN_M = 0.002
const TAXEL_MAX_EXTRA_LEN_M = 0.012
const MM_TO_M = 0.001

interface FingerEntry {
  group: THREE.Group // the sensor frame
  resultant: THREE.ArrowHelper
  centroid: THREE.Vector3
  taxelPositions: THREE.Vector3[] // meters, sensor frame
  shafts: THREE.InstancedMesh
  heads: THREE.InstancedMesh
}

const UP = new THREE.Vector3(0, 1, 0)

export class ForceArrowLayer {
  private entries = new Map<Finger, FingerEntry>()
  private resultantVisible = false
  private taxelsVisible = false

  // scratch
  private v = new THREE.Vector3()
  private q = new THREE.Quaternion()
  private m = new THREE.Matrix4()
  private s = new THREE.Vector3()
  private color = new THREE.Color()

  constructor(
    robot: URDFRobot,
    fingertips: Record<string, FingertipEntry>,
    mounts: SensorMounts | null,
    geometry: TaxelGeometry | null,
  ) {
    if (!mounts) return
    const shaftGeometry = new THREE.CylinderGeometry(0.0004, 0.0004, 1, 5)
    shaftGeometry.translate(0, 0.5, 0) // base at origin, +Y up, unit height
    const headGeometry = new THREE.ConeGeometry(0.0011, 0.0028, 6)
    headGeometry.translate(0, 0.0014, 0)

    for (const [finger, mount] of Object.entries(mounts)) {
      const parentLink = robot.links[fingertips[finger]?.parent_link]
      if (!parentLink) continue

      const group = new THREE.Group()
      group.name = `sensor-frame-${finger}`
      group.matrixAutoUpdate = false
      // Row-major 4x4 from the backend; Matrix4.set takes row-major args.
      const rows = mount.matrix
      group.matrix.set(
        rows[0][0], rows[0][1], rows[0][2], rows[0][3],
        rows[1][0], rows[1][1], rows[1][2], rows[1][3],
        rows[2][0], rows[2][1], rows[2][2], rows[2][3],
        rows[3][0], rows[3][1], rows[3][2], rows[3][3],
      )
      parentLink.add(group)

      const taxelPositions = (geometry?.[finger]?.positions ?? []).map(
        ([x, y, z]) => new THREE.Vector3(x * MM_TO_M, y * MM_TO_M, z * MM_TO_M),
      )
      const centroid = taxelPositions
        .reduce((acc, p) => acc.add(p), new THREE.Vector3())
        .divideScalar(Math.max(taxelPositions.length, 1))

      const resultant = new THREE.ArrowHelper(
        UP, centroid, 0.01, 0xffffff, 0.006, 0.004)
      resultant.visible = false
      group.add(resultant)

      const count = Math.max(taxelPositions.length, 1)
      // toneMapped: false, as THREE.ArrowHelper already does for the
      // resultant below. R3F's Canvas turns on ACES filmic tone mapping,
      // which is meant for scene radiance and crushes saturated primaries —
      // it was taking the heat ramp's full-scale red down to a near-black
      // maroon. These arrows are an instrument reading, not lit geometry:
      // the colour that comes out of getArrowColor2D is the colour that has
      // to reach the screen, or the same force reads as one colour here, a
      // brighter one on the resultant arrow, and a third in the 2D taxel map.
      const shaftMaterial = new THREE.MeshBasicMaterial({ toneMapped: false })
      const headMaterial = new THREE.MeshBasicMaterial({ toneMapped: false })
      const shafts = new THREE.InstancedMesh(shaftGeometry, shaftMaterial, count)
      const heads = new THREE.InstancedMesh(headGeometry, headMaterial, count)
      shafts.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      heads.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
      shafts.frustumCulled = false
      heads.frustumCulled = false
      shafts.visible = false
      heads.visible = false
      group.add(shafts)
      group.add(heads)

      this.entries.set(finger as Finger, {
        group, resultant, centroid, taxelPositions, shafts, heads,
      })
    }
  }

  get available(): boolean {
    return this.entries.size > 0
  }

  setResultantVisible(visible: boolean): void {
    this.resultantVisible = visible
    for (const entry of this.entries.values()) {
      if (!visible) entry.resultant.visible = false
    }
  }

  setTaxelsVisible(visible: boolean): void {
    this.taxelsVisible = visible
    for (const entry of this.entries.values()) {
      entry.shafts.visible = visible
      entry.heads.visible = visible
    }
  }

  updateResultants(
    forces: Partial<Record<Finger, Vec3>> | null,
    scheme: ArrowColorScheme,
    threshold = 0,
  ): void {
    if (!this.resultantVisible) return
    const minN = Math.max(RESULTANT_MIN_N, threshold)
    for (const [finger, entry] of this.entries) {
      const force = forces?.[finger]
      if (!force) {
        entry.resultant.visible = false
        continue
      }
      const [fx, fy, fz] = force
      const magnitude = Math.sqrt(fx * fx + fy * fy + fz * fz)
      if (magnitude < minN) {
        entry.resultant.visible = false
        continue
      }
      // The resultant is its own per-finger reading, so it scales like the 2D
      // dial does — not against a per-taxel peak.
      const normalized = Math.min(magnitude / MAX_FORCE_SCALE, 1)
      this.v.set(fx, fy, fz).normalize()
      const length = 0.006 + normalized * RESULTANT_MAX_LEN_M
      entry.resultant.position.copy(entry.centroid)
      entry.resultant.setDirection(this.v)
      entry.resultant.setLength(length, length * 0.3, length * 0.2)
      this.color.set(getArrowColor2D(scheme, normalized))
      entry.resultant.setColor(this.color)
      entry.resultant.visible = true
    }
  }

  updateTaxels(
    taxels: Partial<Record<Finger, Vec3[]>> | null,
    scheme: ArrowColorScheme,
    threshold = 0,
  ): void {
    if (!this.taxelsVisible) return
    const minN = Math.max(TAXEL_MIN_N, threshold)
    for (const [finger, entry] of this.entries) {
      const maxForce = maxTaxelForce(finger)
      const forces = taxels?.[finger]
      const n = Math.min(
        forces?.length ?? 0,
        entry.taxelPositions.length,
        entry.shafts.count,
      )
      for (let i = 0; i < n; i++) {
        const [fx, fy, fz] = forces![i]
        const magnitude = Math.sqrt(fx * fx + fy * fy + fz * fz)
        const position = entry.taxelPositions[i]
        if (magnitude < minN) {
          this.m.makeScale(0, 0, 0) // hide this instance
          entry.shafts.setMatrixAt(i, this.m)
          entry.heads.setMatrixAt(i, this.m)
          continue
        }
        const normalized = Math.min(magnitude / maxForce, 1)
        const length = TAXEL_BASE_LEN_M + normalized * TAXEL_MAX_EXTRA_LEN_M
        this.v.set(fx, fy, fz).normalize()
        this.q.setFromUnitVectors(UP, this.v)
        this.s.set(1, length, 1)
        this.m.compose(position, this.q, this.s)
        entry.shafts.setMatrixAt(i, this.m)
        // Head: unscaled, at the shaft tip, same orientation.
        this.s.set(1, 1, 1)
        this.m.compose(
          this.v.multiplyScalar(length).add(position), this.q, this.s)
        entry.heads.setMatrixAt(i, this.m)
        this.color.set(getArrowColor2D(scheme, normalized))
        entry.shafts.setColorAt(i, this.color)
        entry.heads.setColorAt(i, this.color)
      }
      // Instances beyond the streamed count stay whatever they were; hide
      // them once when the count shrinks.
      for (let i = n; i < entry.shafts.count; i++) {
        this.m.makeScale(0, 0, 0)
        entry.shafts.setMatrixAt(i, this.m)
        entry.heads.setMatrixAt(i, this.m)
      }
      entry.shafts.instanceMatrix.needsUpdate = true
      entry.heads.instanceMatrix.needsUpdate = true
      if (entry.shafts.instanceColor) entry.shafts.instanceColor.needsUpdate = true
      if (entry.heads.instanceColor) entry.heads.instanceColor.needsUpdate = true
    }
  }

  dispose(): void {
    for (const entry of this.entries.values()) {
      entry.group.removeFromParent()
      entry.resultant.dispose()
      entry.shafts.dispose()
      entry.heads.dispose()
    }
    this.entries.clear()
  }
}

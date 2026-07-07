// Fingertip force arrows, attached to the bundle's <finger>_fingertip links
// so they ride the kinematics. Today: resultant mode (one arrow per finger,
// forces interpreted in the fingertip-local frame through a pluggable
// per-finger transform that defaults to identity). Per-taxel mode plugs in
// here once the sensor->fingertip transforms exist (orca_core PR #79 + the
// user's frame work): feed taxel positions + a real `sensorToFingertip`.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { Finger, Vec3 } from '../../api/types'
import type { FingertipEntry } from '../../api/rest'
import type { ArrowColorScheme } from '../../state/appStore'
import { MAX_TAXEL_FORCE } from '../../theme/tokens'
import { getArrowColor2D } from '../tactile/taxelRender'

const MIN_FORCE_N = 0.3
const MAX_ARROW_LEN_M = 0.035

interface ArrowEntry {
  group: THREE.Group
  arrow: THREE.ArrowHelper
  sensorToFingertip: THREE.Matrix4 // pluggable; identity until calibrated
}

export class ForceArrowLayer {
  private entries = new Map<Finger, ArrowEntry>()
  private direction = new THREE.Vector3()
  private color = new THREE.Color()

  constructor(robot: URDFRobot, fingertips: Record<string, FingertipEntry>) {
    for (const [finger, entry] of Object.entries(fingertips)) {
      const link = robot.links[entry.link]
      if (!link) continue
      const group = new THREE.Group()
      group.name = `force-arrows-${finger}`
      const arrow = new THREE.ArrowHelper(
        new THREE.Vector3(0, 0, 1),
        new THREE.Vector3(0, 0, 0),
        0.01,
        0xffffff,
        0.006,
        0.004,
      )
      arrow.visible = false
      group.add(arrow)
      link.add(group)
      this.entries.set(finger as Finger, {
        group,
        arrow,
        sensorToFingertip: new THREE.Matrix4(),
      })
    }
  }

  update(
    forces: Partial<Record<Finger, Vec3>> | null,
    scheme: ArrowColorScheme,
  ): void {
    for (const [finger, entry] of this.entries) {
      const force = forces?.[finger]
      if (!force) {
        entry.arrow.visible = false
        continue
      }
      const [fx, fy, fz] = force
      const magnitude = Math.sqrt(fx * fx + fy * fy + fz * fz)
      if (magnitude < MIN_FORCE_N) {
        entry.arrow.visible = false
        continue
      }
      this.direction
        .set(fx, fy, fz)
        .transformDirection(entry.sensorToFingertip)
        .normalize()
      const normalized = Math.min(magnitude / MAX_TAXEL_FORCE, 1)
      const length = 0.006 + normalized * MAX_ARROW_LEN_M
      entry.arrow.setDirection(this.direction)
      entry.arrow.setLength(length, length * 0.35, length * 0.22)
      this.color.set(getArrowColor2D(scheme, normalized))
      entry.arrow.setColor(this.color)
      entry.arrow.visible = true
    }
  }

  setVisible(visible: boolean): void {
    for (const entry of this.entries.values()) entry.group.visible = visible
  }

  dispose(): void {
    for (const entry of this.entries.values()) {
      entry.group.removeFromParent()
      entry.arrow.dispose()
    }
    this.entries.clear()
  }
}

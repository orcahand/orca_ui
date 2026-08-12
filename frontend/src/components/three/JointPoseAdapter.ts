// The ONLY place degrees become radians. orca_core angles map onto the URDF
// 1:1 (the regenerated orcahand_description shares the convention on both
// sides), so no per-joint correction table is needed — just a ROM clamp.

import type { URDFRobot } from 'urdf-loader'
import type { JointInfo } from '../../api/types'

const DEG2RAD = Math.PI / 180

// Slack each joint drags behind the incoming angle: inside the band it holds
// still, hiding the residual sensor noise; outside it moves by the excess only,
// so it keeps tracking every frame and just trails by the band. Sized per joint
// to sit above that joint's noise — the band costs a trailing offset and twice
// that in backlash on reversal, but does not coarsen motion.
const POSE_SLACK_DEG = 0.1

// The wrist's lever arm magnifies both costs at the fingertips, and it is
// quieter than the fingers, so it holds still on a narrower band.
const SLACK_OVERRIDES: Record<string, number> = { wrist: 0.07 }

export class JointPoseAdapter {
  private robot: URDFRobot
  private roms: Record<string, [number, number]>
  private posed: Record<string, number> = {}

  constructor(robot: URDFRobot, joints: JointInfo[]) {
    this.robot = robot
    this.roms = Object.fromEntries(joints.map((j) => [j.id, j.rom]))
  }

  apply(anglesDeg: Record<string, number>): boolean {
    let changed = false
    for (const joint in anglesDeg) {
      const urdfJoint = this.robot.joints[joint]
      if (!urdfJoint) continue
      let deg = anglesDeg[joint]
      const rom = this.roms[joint]
      if (rom) deg = Math.min(rom[1], Math.max(rom[0], deg))

      const posed = this.posed[joint]
      if (posed !== undefined) {
        const slack = SLACK_OVERRIDES[joint] ?? POSE_SLACK_DEG
        const excess = Math.abs(deg - posed) - slack
        if (excess <= 0) continue
        deg = posed + Math.sign(deg - posed) * excess
      }

      this.posed[joint] = deg
      if (urdfJoint.setJointValue(DEG2RAD * deg)) changed = true
    }
    return changed
  }
}

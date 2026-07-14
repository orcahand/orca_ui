// The ONLY place degrees become radians. orca_core angles map onto the URDF
// 1:1 (the regenerated orcahand_description shares the convention on both
// sides), so no per-joint correction table is needed — just a ROM clamp.

import type { URDFRobot } from 'urdf-loader'
import type { JointInfo } from '../../api/types'

const DEG2RAD = Math.PI / 180

export class JointPoseAdapter {
  private robot: URDFRobot
  private roms: Record<string, [number, number]>

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
      if (urdfJoint.setJointValue(DEG2RAD * deg)) changed = true
    }
    return changed
  }
}

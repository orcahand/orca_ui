// The ONLY place degrees become radians and per-joint {sign, offset_deg}
// corrections apply. The correction table comes from
// /api/model/calibration (orca_ui/models/hand_v2/joint_calibration.yaml),
// re-fetched on demand so the tune-YAML -> refresh loop stays fast.

import type { URDFRobot } from 'urdf-loader'
import type { JointCalibrationEntry, JointInfo } from '../../api/types'

const DEG2RAD = Math.PI / 180

export class JointPoseAdapter {
  private robot: URDFRobot
  private calibration: Record<string, JointCalibrationEntry>
  private roms: Record<string, [number, number]>

  constructor(
    robot: URDFRobot,
    calibration: Record<string, JointCalibrationEntry>,
    joints: JointInfo[],
  ) {
    this.robot = robot
    this.calibration = calibration
    this.roms = Object.fromEntries(joints.map((j) => [j.id, j.rom]))
  }

  setCalibration(calibration: Record<string, JointCalibrationEntry>): void {
    this.calibration = calibration
  }

  apply(anglesDeg: Record<string, number>): boolean {
    let changed = false
    for (const joint in anglesDeg) {
      const urdfJoint = this.robot.joints[joint]
      if (!urdfJoint) continue
      let deg = anglesDeg[joint]
      const rom = this.roms[joint]
      if (rom) deg = Math.min(rom[1], Math.max(rom[0], deg))
      const cal = this.calibration[joint]
      const rad = DEG2RAD * ((cal?.sign ?? 1) * deg + (cal?.offset_deg ?? 0))
      if (urdfJoint.setJointValue(rad)) changed = true
    }
    return changed
  }
}

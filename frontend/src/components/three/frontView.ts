// Stands the hand upright on its tower, palm toward +Z, so every view can open
// face-on from the front. The orientation is read off the model itself:
// fingers point from the middle MCP to its fingertip, and flexing that MCP
// swings the tip toward the palm — so it holds for either side without a
// per-side table.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { JointInfo } from '../../api/types'

const DEG2RAD = Math.PI / 180

// Camera offset from the hand's centre for the opening view: in front of the
// palm, a little above it.
export const FRONT_VIEW = new THREE.Vector3(0, 0.3, 1).normalize()

function handAxes(robot: URDFRobot, joints: JointInfo[]) {
  const joint = robot.joints['middle_mcp']
  const tip = robot.links['middle_fingertip']
  const rom = joints.find((j) => j.id === 'middle_mcp')?.rom
  if (!joint || !tip || !rom) return null
  const flex = Math.abs(rom[1]) >= Math.abs(rom[0]) ? rom[1] : rom[0]
  const previous = joint.angle
  const tipAt = (deg: number) => {
    joint.setJointValue(deg * DEG2RAD)
    robot.updateMatrixWorld(true)
    return tip.getWorldPosition(new THREE.Vector3())
  }
  const straight = tipAt(0)
  const curled = tipAt(flex)
  joint.setJointValue(previous)
  robot.updateMatrixWorld(true)
  const base = joint.getWorldPosition(new THREE.Vector3())
  const fingers = straight.clone().sub(base).normalize()
  const swing = curled.sub(straight)
  const palm = swing.sub(fingers.clone().multiplyScalar(swing.dot(fingers)))
  if (palm.lengthSq() < 1e-12) return null
  return { fingers, palm: palm.normalize() }
}

// Rotate fingers → +Y and palm → +Z, then rest the tower on the y = 0 floor.
export function standUpright(robot: URDFRobot, joints: JointInfo[]): void {
  const axes = handAxes(robot, joints)
  if (!axes) return
  const { fingers, palm } = axes
  const from = new THREE.Matrix4().makeBasis(fingers, palm, fingers.clone().cross(palm))
  const to = new THREE.Matrix4().makeBasis(
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(1, 0, 0),
  )
  const rotation = new THREE.Quaternion().setFromRotationMatrix(to.multiply(from.transpose()))
  robot.quaternion.premultiply(rotation)
  robot.position.set(0, 0, 0)
  robot.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(robot)
  robot.position.set(-(box.min.x + box.max.x) / 2, -box.min.y, -(box.min.z + box.max.z) / 2)
  robot.updateMatrixWorld(true)
}

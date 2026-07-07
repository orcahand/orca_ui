// Headless smoke check: parse the generated hand.urdf through the real
// urdf-loader code path (as the browser would) and verify the joint map.
// Usage: node scripts/check-urdf.mjs [../orca_ui/models/hand_v2/right/hand.urdf]

import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import * as THREE from 'three'
import URDFLoader from 'urdf-loader'

const dom = new JSDOM()
globalThis.DOMParser = dom.window.DOMParser
globalThis.XMLSerializer = dom.window.XMLSerializer
globalThis.document = dom.window.document
globalThis.Document = dom.window.Document
globalThis.XMLDocument = dom.window.XMLDocument
globalThis.Element = dom.window.Element
globalThis.Node = dom.window.Node

const CANONICAL = [
  'wrist',
  'thumb_cmc', 'thumb_abd', 'thumb_mcp', 'thumb_dip',
  'index_abd', 'index_mcp', 'index_pip',
  'middle_abd', 'middle_mcp', 'middle_pip',
  'ring_abd', 'ring_mcp', 'ring_pip',
  'pinky_abd', 'pinky_mcp', 'pinky_pip',
]
const FINGERTIPS = ['thumb', 'index', 'middle', 'ring', 'pinky'].map(
  (f) => `${f}_fingertip`,
)

const urdfPath =
  process.argv[2] ?? '../orca_ui/models/hand_v2/right/hand.urdf'
const content = readFileSync(urdfPath, 'utf-8')

const loader = new URDFLoader()
// v0.13 runtime signature: (path, manager, material, done)
loader.loadMeshCb = (...args) => {
  const done = args[args.length - 1]
  done(new THREE.Mesh(new THREE.BoxGeometry(0.01, 0.01, 0.01)))
}
const robot = loader.parse(content)

const jointNames = Object.keys(robot.joints)
const revolute = jointNames.filter(
  (n) => robot.joints[n].jointType === 'revolute',
)

let failures = 0
const check = (ok, message) => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${message}`)
  if (!ok) failures += 1
}

check(revolute.length === 17, `17 revolute joints (got ${revolute.length})`)
for (const joint of CANONICAL) {
  check(joint in robot.joints, `joint ${joint} present`)
}
for (const link of FINGERTIPS) {
  check(link in robot.links, `fingertip link ${link} present`)
}

// Joint values apply and change the pose.
const tip = robot.links['index_fingertip']
robot.updateMatrixWorld(true)
const before = new THREE.Vector3().setFromMatrixPosition(tip.matrixWorld)
robot.joints['index_mcp'].setJointValue(THREE.MathUtils.degToRad(60))
robot.updateMatrixWorld(true)
const after = new THREE.Vector3().setFromMatrixPosition(tip.matrixWorld)
const moved = before.distanceTo(after)
check(moved > 0.005, `index_mcp=60° moves index fingertip (${(moved * 1000).toFixed(1)} mm)`)

// Ghost clone preserves the joint map (the makeGhost precondition).
const ghost = robot.clone(true)
check(
  ghost.joints && Object.keys(ghost.joints).length === jointNames.length,
  `clone(true) preserves ${jointNames.length} joints`,
)
ghost.joints['index_mcp'].setJointValue(0.2)
check(
  Math.abs(robot.joints['index_mcp'].angle - THREE.MathUtils.degToRad(60)) < 1e-6,
  'ghost joint values are independent of the solid robot',
)

console.log(failures === 0 ? '\nAll URDF checks passed.' : `\n${failures} FAILURES`)
process.exit(failures === 0 ? 0 : 1)

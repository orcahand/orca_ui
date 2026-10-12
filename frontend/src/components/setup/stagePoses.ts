// What the hand looks like for each range-check stage (see RangeStage in
// orca_core's guided_tension): the fingers out of the way are parked at the
// far end of their abduction, the finger under test sits mid-range, and outside
// the thumb stage the thumb swings fully out. Which end is "toward the thumb" or
// "out" is read off the model, so it holds for both sides.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { JointInfo } from '../../api/types'

export type AbductionEnd = 0 | 1 // index into the joint's ROM
export type TowardThumb = Record<string, AbductionEnd>

const DEG2RAD = Math.PI / 180
const SPREAD_FINGERS = ['index', 'middle', 'ring', 'pinky'] as const
const BENT_DEG = 45
const THUMB_OUT_JOINTS = ['thumb_cmc', 'thumb_abd']

const clamp = (deg: number, rom: [number, number]) => Math.min(rom[1], Math.max(rom[0], deg))
const mid = (rom: [number, number]) => (rom[0] + rom[1]) / 2

export function fingerOf(joint: string): string {
  return joint.split('_')[0]
}

// For each finger, the ROM end of its abduction that swings it toward the
// thumb: the end whose fingertip lands further along the pinky → index line.
export function towardThumb(robot: URDFRobot, joints: JointInfo[]): TowardThumb {
  const byId = Object.fromEntries(joints.map((j) => [j.id, j]))
  const at = (link: string) => robot.links[link]?.getWorldPosition(new THREE.Vector3())
  robot.updateMatrixWorld(true)
  const indexBase = at('index_pp')
  const pinkyBase = at('pinky_pp')
  const out: TowardThumb = {}
  if (!indexBase || !pinkyBase) return out
  const axis = indexBase.sub(pinkyBase).normalize()
  for (const finger of SPREAD_FINGERS) {
    const abd = robot.joints[`${finger}_abd`]
    const info = byId[`${finger}_abd`]
    if (!abd || !info) continue
    const previous = abd.angle
    const reach = (deg: number) => {
      abd.setJointValue(deg * DEG2RAD)
      robot.updateMatrixWorld(true)
      return at(`${finger}_fingertip`)?.dot(axis) ?? 0
    }
    out[finger] = reach(info.rom[1]) > reach(info.rom[0]) ? 1 : 0
    abd.setJointValue(previous)
  }
  robot.updateMatrixWorld(true)
  return out
}

// For thumb_cmc and thumb_abd, the ROM end that swings the thumb tip furthest
// from the middle finger's base, keyed by joint id.
export function thumbOut(robot: URDFRobot, joints: JointInfo[]): TowardThumb {
  const byId = Object.fromEntries(joints.map((j) => [j.id, j]))
  const at = (link: string) => robot.links[link]?.getWorldPosition(new THREE.Vector3())
  robot.updateMatrixWorld(true)
  const middleBase = at('middle_pp')
  const out: TowardThumb = {}
  if (!middleBase) return out
  for (const id of THUMB_OUT_JOINTS) {
    const joint = robot.joints[id]
    const info = byId[id]
    if (!joint || !info) continue
    const previous = joint.angle
    const reach = (deg: number) => {
      joint.setJointValue(deg * DEG2RAD)
      robot.updateMatrixWorld(true)
      return at('thumb_fingertip')?.distanceTo(middleBase) ?? 0
    }
    out[id] = reach(info.rom[1]) > reach(info.rom[0]) ? 1 : 0
    joint.setJointValue(previous)
  }
  robot.updateMatrixWorld(true)
  return out
}

// Fingers parked toward / away from the thumb, per stage key.
const PARKED: Record<string, { toward: string[]; away: string[] }> = {
  thumb_index: { toward: [], away: ['middle', 'ring', 'pinky'] },
  middle: { toward: ['index'], away: ['ring', 'pinky'] },
  ring: { toward: ['index', 'middle'], away: ['pinky'] },
  pinky: { toward: ['index', 'middle', 'ring'], away: [] },
}

export function stagePose(
  stageKey: string | null,
  joints: JointInfo[],
  toward: TowardThumb,
): Record<string, number> {
  const pose: Record<string, number> = {}
  const parked = stageKey ? PARKED[stageKey] : undefined
  for (const joint of joints) {
    const finger = fingerOf(joint.id)
    if (joint.id === 'wrist') pose[joint.id] = joint.neutral
    else if (!parked) pose[joint.id] = mid(joint.rom)
    else if (finger === 'thumb' && stageKey !== 'thumb_index') {
      pose[joint.id] = THUMB_OUT_JOINTS.includes(joint.id)
        ? joint.rom[toward[joint.id] ?? 1]
        : clamp(0, joint.rom)
    } else if (finger === 'thumb') pose[joint.id] = mid(joint.rom)
    else if (stageKey === 'thumb_index' && finger === 'index') {
      pose[joint.id] = joint.id.endsWith('_abd') ? mid(joint.rom) : clamp(BENT_DEG, joint.rom)
    } else if (parked.toward.includes(finger) || parked.away.includes(finger)) {
      const end = toward[finger] ?? 1
      pose[joint.id] = joint.id.endsWith('_abd')
        ? joint.rom[parked.toward.includes(finger) ? end : ((1 - end) as AbductionEnd)]
        : clamp(0, joint.rom)
    } else pose[joint.id] = mid(joint.rom)
  }
  return pose
}

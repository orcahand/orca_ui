// Which joint each spool position on the tower drives. Positions name the nodes
// in models/hand_v2/<side>/tower_spools.glb (scripts/build_tower_model.py):
// <face><col><row>, face F = HullFront side, B = HullBack side, row 1 at the
// wrist end. The motor ids come from the hand's config.

export type TowerFace = 'F' | 'B'

export const towerUrl = (side: 'left' | 'right') => `/assets/hand/${side}/tower_spools.glb`

const RIGHT_SPOOL_JOINT: Record<string, string> = {
  F11: 'thumb_cmc',
  F12: 'thumb_dip',
  F13: 'thumb_mcp',
  F14: 'thumb_abd',
  F21: 'middle_mcp',
  F22: 'pinky_pip',
  F23: 'pinky_mcp',
  F24: 'pinky_abd',
  B11: 'index_pip',
  B12: 'index_mcp',
  B13: 'index_abd',
  B14: 'middle_abd',
  B21: 'middle_pip',
  B22: 'ring_pip',
  B23: 'ring_mcp',
  B24: 'ring_abd',
}

// The left tower is the right one mirrored, but the model reuses the right
// tower's geometry, so on a left hand each joint sits in the other column.
export function spoolJoint(side: 'left' | 'right', pos: string): string {
  const col = side === 'left' ? (pos[1] === '1' ? '2' : '1') : pos[1]
  return RIGHT_SPOOL_JOINT[`${pos[0]}${col}${pos[2]}`]
}

export const FACE_LABEL: Record<TowerFace, string> = {
  F: 'Front · palm side',
  B: 'Back',
}

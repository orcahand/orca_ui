// The coupling between joints and motors, as the backend sees it: joints
// that share motors form a coupling, and q = B · (shaft − zero) with B
// square, one row per joint from its terms. The page reads joint angles off
// the live shafts through B directly; it inverts B only to know whether the
// backend will be able to drive the coupling. Works on joints whose terms
// are already resolved from tendons to motors (see fingerStore.resolve).

export interface MotorTerm {
  motor: number
  gain: number
}

export interface MotorJoint {
  name: string
  group: string
  open_deg: number | null
  closed_deg: number | null
  terms: MotorTerm[]
  // Tendons of this joint that are not wound on any motor.
  unresolved: string[]
}

export interface Coupling {
  joints: MotorJoint[]
  motors: number[]
  // One row per joint: joint degrees per shaft degree of each motor.
  matrix: number[][]
  // false when the coupling is not square or cannot be inverted.
  solvable: boolean
}

/** Gauss-Jordan inverse for the small square matrices a hand produces. */
function invert(a: number[][]): number[][] | null {
  const n = a.length
  const m = a.map((row, i) => [...row, ...row.map((_, j) => (i === j ? 1 : 0))])
  for (let col = 0; col < n; col++) {
    let pivot = col
    for (let r = col + 1; r < n; r++) if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r
    if (Math.abs(m[pivot][col]) < 1e-9) return null
    ;[m[col], m[pivot]] = [m[pivot], m[col]]
    const p = m[col][col]
    for (let c = 0; c < 2 * n; c++) m[col][c] /= p
    for (let r = 0; r < n; r++) {
      if (r === col) continue
      const f = m[r][col]
      if (f === 0) continue
      for (let c = 0; c < 2 * n; c++) m[r][c] -= f * m[col][c]
    }
  }
  return m.map((row) => row.slice(n))
}

/** Joints grouped by the motors they share, transitively. */
export function couplingsOf(joints: MotorJoint[]): Coupling[] {
  const parent = joints.map((_, i) => i)
  const find = (i: number): number => (parent[i] === i ? i : (parent[i] = find(parent[i])))
  const owner = new Map<number, number>()
  joints.forEach((joint, i) => {
    for (const term of joint.terms) {
      const first = owner.get(term.motor)
      if (first === undefined) owner.set(term.motor, i)
      else parent[find(i)] = find(first)
    }
  })
  const groups = new Map<number, MotorJoint[]>()
  joints.forEach((joint, i) => {
    const root = find(i)
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root)!.push(joint)
  })
  return [...groups.values()].map((members) => {
    const motors = [...new Set(members.flatMap((j) => j.terms.map((t) => t.motor)))].sort((a, b) => a - b)
    const matrix = members.map((joint) =>
      motors.map((motor) => joint.terms.find((t) => t.motor === motor)?.gain ?? 0),
    )
    const solvable = motors.length === members.length && motors.length > 0 && invert(matrix) !== null
    return { joints: members, motors, matrix, solvable }
  })
}

/** Why a coupling cannot be driven, or null when it can. */
export function couplingProblem(c: Coupling): string | null {
  const loose = c.joints.flatMap((j) => j.unresolved)
  if (loose.length) return `tendon ${loose.join(', ')} not on a motor`
  if (c.motors.length === 0) return 'no tendon'
  if (c.motors.length !== c.joints.length)
    return `${c.joints.length} joint(s) on ${c.motors.length} motor(s)`
  if (!c.solvable) return 'singular coupling'
  return null
}

/** Joint angles (degrees) from live shaft positions, by joint name; a joint
 *  whose motor has no reading is absent. */
export function jointAnglesOf(
  couplings: Coupling[],
  zeros: Record<string, number>,
  positions: Record<string, number>,
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const c of couplings) {
    const shaft = c.motors.map((m) => {
      const p = positions[String(m)]
      return p === undefined ? NaN : p - (zeros[String(m)] ?? 0)
    })
    if (shaft.some((v) => Number.isNaN(v))) continue
    c.joints.forEach((joint, j) => {
      out[joint.name] = c.matrix[j].reduce((sum, b, i) => sum + b * shaft[i], 0)
    })
  }
  return out
}

/** Gains for an MCP/PIP pair on a sum/difference tendon routing, as the
 *  formula reads:  q_MCP = r_s (θ_U + θ_C) / r_MCP,   q_PIP = r_s (θ_U − θ_C) / r_PIP. */
export function differentialGains(spoolRadius: number, radiusMcp: number, radiusPip: number) {
  const round = (v: number) => Math.round(v * 10000) / 10000
  return { mcp: round(spoolRadius / radiusMcp), pip: round(spoolRadius / radiusPip) }
}

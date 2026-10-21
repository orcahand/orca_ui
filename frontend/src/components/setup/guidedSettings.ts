// Per-viewer guided-tensioning thresholds, remembered so a fine-tuned set
// carries over to the next run. Fraction scoring (the ccc page) keeps a pass
// fraction per joint group; slack scoring (the kai page) a slack tolerance in
// motor degrees. Groups and bounds mirror PASS_GROUPS / PASS_BOUNDS_* in
// orca_ui/hand/operations/guided_tension.py.

export type PassGroup = 'ap' | 'mcp' | 'pip'
export type PassFractions = Record<PassGroup, number>
export type PassSlack = Record<PassGroup, number>

export const PASS_GROUPS: { key: PassGroup; label: string; hint: string }[] = [
  { key: 'ap', label: 'APs', hint: 'abductions + thumb cmc' },
  { key: 'mcp', label: 'MCPs', hint: 'all MCP joints' },
  { key: 'pip', label: 'PIPs', hint: 'PIPs + thumb dip' },
]
export const PASS_BOUNDS_PCT = [10, 100] as const
export const DEFAULT_PASS: PassFractions = { ap: 0.8, mcp: 0.8, pip: 0.8 }
export const PASS_BOUNDS_DEG = [0.5, 30] as const
export const DEFAULT_PASS_SLACK: PassSlack = { ap: 3, mcp: 5, pip: 5 }

// The pass is 80 % of the reference hand's travel.
const PASS_KEY = 'orca.guidedTension.passFractions.v2'
const SLACK_KEY = 'orca.guidedTension.passSlackDeg'

// Mirrors joint_group() in orca_ui/hand/operations/guided_tension.py.
export function jointGroup(joint: string): PassGroup {
  if (joint.endsWith('_abd') || joint === 'thumb_cmc') return 'ap'
  return joint.endsWith('_mcp') ? 'mcp' : 'pip'
}

export function loadPassFractions(): PassFractions {
  try {
    const stored = JSON.parse(localStorage.getItem(PASS_KEY) ?? 'null')
    if (stored && typeof stored === 'object') {
      const valid = PASS_GROUPS.filter(({ key }) => {
        const pct = Number(stored[key]) * 100
        return pct >= PASS_BOUNDS_PCT[0] && pct <= PASS_BOUNDS_PCT[1]
      })
      return { ...DEFAULT_PASS, ...Object.fromEntries(valid.map(({ key }) => [key, Number(stored[key])])) }
    }
  } catch {
    /* unreadable: fall back to the defaults */
  }
  return DEFAULT_PASS
}

export function savePassFractions(passes: PassFractions): void {
  try {
    localStorage.setItem(PASS_KEY, JSON.stringify(passes))
  } catch {
    /* storage unavailable: the values last this run */
  }
}

const inDegreeBounds = (v: unknown) =>
  typeof v === 'number' && v >= PASS_BOUNDS_DEG[0] && v <= PASS_BOUNDS_DEG[1]

export function loadPassSlack(): PassSlack {
  try {
    const stored = JSON.parse(localStorage.getItem(SLACK_KEY) ?? 'null')
    if (stored && typeof stored === 'object') {
      const valid = PASS_GROUPS.filter(({ key }) => inDegreeBounds(stored[key]))
      return { ...DEFAULT_PASS_SLACK, ...Object.fromEntries(valid.map(({ key }) => [key, stored[key]])) }
    }
  } catch {
    /* unreadable: fall back to the defaults */
  }
  return DEFAULT_PASS_SLACK
}

export function savePassSlack(passes: PassSlack): void {
  try {
    localStorage.setItem(SLACK_KEY, JSON.stringify(passes))
  } catch {
    /* storage unavailable: the values last this run */
  }
}

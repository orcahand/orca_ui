// Per-viewer guided-tensioning thresholds, remembered so a fine-tuned set
// carries over to the next run. Groups and bounds mirror PASS_GROUPS /
// PASS_BOUNDS in orca_ui/hand/operations/guided_tension.py.

export type PassGroup = 'ap' | 'mcp' | 'pip'
export type PassFractions = Record<PassGroup, number>

export const PASS_GROUPS: { key: PassGroup; label: string; hint: string }[] = [
  { key: 'ap', label: 'APs', hint: 'abductions + thumb cmc' },
  { key: 'mcp', label: 'MCPs', hint: 'all MCP joints' },
  { key: 'pip', label: 'PIPs', hint: 'PIPs + thumb dip' },
]
export const PASS_BOUNDS_PCT = [10, 100] as const
export const DEFAULT_PASS: PassFractions = { ap: 0.85, mcp: 0.85, pip: 0.85 }

const PASS_KEY = 'orca.guidedTension.passFractions'

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
    /* storage unavailable: the values just aren't remembered */
  }
}

// Mirrors joint_group() in orca_ui/hand/operations/guided_tension.py.
export function jointGroup(joint: string): PassGroup {
  if (joint.endsWith('_abd') || joint === 'thumb_cmc') return 'ap'
  return joint.endsWith('_mcp') ? 'mcp' : 'pip'
}

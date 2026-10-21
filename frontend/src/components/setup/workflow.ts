// The setup workflow the chart under the step tiles shows: one entry per step,
// in order, with what happens and why. These are the defaults; the chart's
// edit mode lets the operator change any text or colour in the browser
// (kept in localStorage, "Reset" brings these back).

export interface WorkflowStep {
  key: string
  title: string
  // Short label under the title in the chart.
  note: string
  // Box colour (any CSS colour).
  color: string
  what: string
  why: string
  // What the operator does with the outcome.
  todo: string
}

export const WORKFLOW_VERSION = 2
export const WORKFLOW_KEY = `orca.setup.workflow.v${WORKFLOW_VERSION}`

export const DEFAULT_WORKFLOW: WorkflowStep[] = [
  {
    key: 'slack',
    title: 'Slack test',
    note: 'half a turn each way',
    color: '#64748b',
    what:
      'Every finger motor winds up to half a turn in each direction at a current too low to move a tensioned joint. The degrees a spool turns before it stalls are its slack.',
    why:
      'A spool that completes the half turn has nothing holding it: tensioning and calibrating would unspool the tendon. The hand is blocked until it passes; everything else starts from a passed slack test.',
    todo:
      'Passed (no spool ran the half turn): move on to the tension check. A spool that completed the half turn has no tension left to ratchet against: unmount that top spool and reattach it with more inherent tension in the system, as the assembly manual describes, then run the slack test again.',
  },
  {
    key: 'check',
    title: 'Tension check',
    note: 'pose, then probe',
    color: '#a78bfa',
    what:
      'Torque off, you bring the hand to the mid-range pose shown. Then the joints of one group ramp their motor current together until they move, both directions, each motor driven back in between. One pass, compared with the reference hand.',
    why:
      'Runs without a calibration, so it fits between rounds. 90–110 % of the reference is green, 70–90 % yellow (ratchet it), under 70 % red (loose), over 110 % grey: tighter than the reference and left alone. The exact check is the sweep after calibration.',
    todo:
      'Green on every tendon: go on to calibrate. Yellow and red tendons: press Continue to tensioning and ratchet them by the clicks listed. Grey tendons are tighter than the reference; leave them, the sweep after calibration decides.',
  },
  {
    key: 'ratchet',
    title: 'Ratchet',
    note: 'the listed spools, x clicks',
    color: '#f59e0b',
    what:
      'The motors turn counterclockwise and hold at the tension current. The dialog lists the tendons the check found loose, loosest first, with the clicks each needs; you turn those top spools and press Done.',
    why:
      'Ratcheting only what the check flagged, by a known number of clicks, keeps the hand from being over-tensioned joint by joint.',
    todo:
      'Hulls off. Turn the listed top spools clockwise by the clicks shown, stop as soon as the tendon feels firm, then press Done. The fingers get moved next.',
  },
  {
    key: 'move',
    title: 'Move fingers',
    note: 'range check, finger by finger',
    color: '#22d3ee',
    what:
      'One finger at a time: the motors hold a pose, you drive the finger through its whole range by hand, the console scores how far each spool followed. Then the tension check and the ratchet again, until the check is green.',
    why:
      'Moving the fingers seats the tendons after the ratchet; the score and the next check show what the clicks changed.',
    todo:
      'Pose the finger like the model, press Continue, drive it by hand through its whole range to both ends, then Next. After the last finger the tension check runs again.',
  },
  {
    key: 'calibrate',
    title: 'Calibrate',
    note: 'automatic or manual',
    color: '#34d399',
    what:
      'Automatic: the motors drive every joint to both hard stops and record the motor positions there. Manual: torque off, you hold each joint on its stops and press Enter.',
    why:
      'Tensioning changes the tendon lengths, so the limits must be measured after it. Everything that follows runs between these limits.',
    todo:
      'Keep clear while the motors drive to the stops (automatic). For a manual calibration hold each joint on its stops by hand and press Enter per step. Then measure the tension.',
  },
  {
    key: 'measure',
    title: 'Tension sweep',
    note: 'limit to limit, current recorded',
    color: '#0ea5e9',
    what:
      'Collision-free groups of joints are driven slowly from one calibrated limit to the other and back while each motor current is recorded, the thumb parked away from the fingers. The mean over the middle of the travel is the tendon load, compared with the reference sweep per joint and side.',
    why:
      'This is the exact tension measurement: more than 20 % off the reference is red, 10 to 20 % yellow, closer green. A tendon still low goes back to the ratchet, then calibrate and measure again.',
    todo:
      'Keep clear of the hand. All green: go on to Run. A tendon low or under: press Tension again, ratchet it, then calibrate and measure once more.',
  },
  {
    key: 'again',
    title: 'Tension again',
    note: 'only if flagged',
    color: '#f59e0b',
    what:
      'Guided tensioning opens at the ratchet step with the tendons the measurement found low. After the clicks the hand is calibrated and measured once more.',
    why:
      'The measurement is only valid between fresh limits, so every ratchet after a calibration needs a new calibration and a new measurement.',
    todo:
      'Ratchet the listed spools by the clicks shown, press Done, then calibrate again and measure again.',
  },
  {
    key: 'run',
    title: 'Run',
    note: 'the long test',
    color: '#94a3b8',
    what: 'The calibrated hand runs its joints through their ranges in a collision-free loop for minutes.',
    why: 'New tendons settle in the first minutes of motion; running before use keeps the calibration honest.',
    todo:
      'Pick the minutes and the speed, start, and keep the hand free. Done: the hand is ready to use.',
  },
]

// Where each box sits on the chart (column, row): the tensioning loop on the
// first row, the calibration loop on the second, Run at the end.
export const WORKFLOW_LAYOUT: Record<string, [col: number, row: number]> = {
  slack: [0, 0],
  check: [1, 0],
  ratchet: [2, 0],
  move: [3, 0],
  calibrate: [1, 1],
  measure: [2, 1],
  run: [3, 1],
  again: [2, 2],
}
// Arrows: from → to, with the condition on the arrow.
export const WORKFLOW_ARROWS: { from: string; to: string; label?: string; kind: 'next' | 'loop' | 'down' }[] = [
  { from: 'slack', to: 'check', label: 'passed', kind: 'next' },
  { from: 'check', to: 'ratchet', label: 'yellow tendons', kind: 'next' },
  { from: 'ratchet', to: 'move', kind: 'next' },
  { from: 'move', to: 'check', label: 'check again', kind: 'loop' },
  { from: 'check', to: 'calibrate', label: 'all green', kind: 'down' },
  { from: 'calibrate', to: 'measure', kind: 'next' },
  { from: 'measure', to: 'run', label: 'all green', kind: 'next' },
  { from: 'measure', to: 'again', label: 'a tendon low', kind: 'down' },
  { from: 'again', to: 'calibrate', label: 'calibrate and measure again', kind: 'loop' },
]

// Steps that loop back, with what ends the loop.
export const WORKFLOW_LOOPS: { from: string; to: string; label: string }[] = [
  { from: 'move', to: 'check', label: 'until the check is green' },
  { from: 'again', to: 'calibrate', label: 'calibrate and measure again' },
]

export function loadWorkflow(): WorkflowStep[] {
  try {
    const stored = JSON.parse(localStorage.getItem(WORKFLOW_KEY) ?? 'null')
    if (Array.isArray(stored) && stored.length === DEFAULT_WORKFLOW.length) {
      return DEFAULT_WORKFLOW.map((d, i) => {
        const s = stored[i] ?? {}
        const pick = (k: keyof WorkflowStep) => (typeof s[k] === 'string' ? (s[k] as string) : d[k])
        return { key: d.key, title: pick('title'), note: pick('note'), color: pick('color'), what: pick('what'), why: pick('why'), todo: pick('todo') }
      })
    }
  } catch {
    /* unreadable: the defaults */
  }
  return DEFAULT_WORKFLOW
}

export function saveWorkflow(steps: WorkflowStep[] | null): void {
  try {
    if (steps) localStorage.setItem(WORKFLOW_KEY, JSON.stringify(steps))
    else localStorage.removeItem(WORKFLOW_KEY)
  } catch {
    /* storage unavailable: the edit lasts this page load */
  }
}

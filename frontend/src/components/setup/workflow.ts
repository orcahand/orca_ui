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

export const WORKFLOW_VERSION = 4
export const WORKFLOW_KEY = `orca.setup.workflow.v${WORKFLOW_VERSION}`

export const DEFAULT_WORKFLOW: WorkflowStep[] = [
  {
    key: 'slack',
    title: 'Slack test',
    note: 'hold each joint',
    color: '#64748b',
    what:
      'You hold one joint at a time so it cannot move while its motor winds each way at low current. Everything the spool turns before the tendons go taut is slack, shown in motor degrees and as ratchet clicks.',
    why:
      'A joint with more than half a turn of slack would unspool its tendon when calibrated, so the hand is blocked until it passes. The click counts say how much the ratchet has to take up before the tendons are even taut.',
    todo:
      'Passed: go on to tensioning, the clicks shown are the minimum per joint. Failed: ratchet out the clicks listed, or unmount the top spool and reattach it with more inherent tension as the assembly manual describes, then test again.',
  },
  {
    key: 'ratchet',
    title: 'Ratchet',
    note: 'the listed spools, ~x clicks',
    color: '#f59e0b',
    what:
      'The motors turn counterclockwise and hold at the tension current. The dialog lists the joints still short of their travel, each with the clicks that missing travel needs, rounded down.',
    why:
      'Rounding down keeps every round a little loose. Clicks only ever add tension, so it is safer to stop short and let the sweep after calibration count the last ones.',
    todo:
      'Hulls off. Turn the listed top spools clockwise by the clicks shown, stop early if a tendon feels firm, then press Done. The fingers get moved next.',
  },
  {
    key: 'move',
    title: 'Move fingers',
    note: 'range check, finger by finger',
    color: '#22d3ee',
    what:
      'One finger at a time: the motors hold a pose, you drive the finger through its whole range by hand, and the console scores how much of the expected motor travel each spool followed.',
    why:
      'A spool that follows only part of the travel still has slack: the missing travel, in motor degrees, is what the next ratchet round takes up.',
    todo:
      'Pose the finger like the model, press Continue, drive it by hand to both ends, then Next. Joints short of their target go back to the ratchet; when every joint passes, calibrate.',
  },
  {
    key: 'calibrate',
    title: 'Calibrate',
    note: 'automatic or manual',
    color: '#34d399',
    what:
      'Automatic: the motors drive every joint to both hard stops and record the motor positions there. Manual: torque off, you hold each joint on its stops and press Enter.',
    why:
      'Tensioning changes the tendon lengths, so the limits must be measured after it. The sweep runs between these limits.',
    todo:
      'Keep clear while the motors drive to the stops (automatic). For a manual calibration hold each joint on its stops by hand and press Enter per step. Then run the tension sweep.',
  },
  {
    key: 'measure',
    title: 'Tension sweep',
    note: 'limit to limit, clicks counted',
    color: '#0ea5e9',
    what:
      'The joints of one kind are driven slowly from one calibrated limit to the other and back while each motor current is recorded. The friction along the travel is compared with the reference hand, and a joint below 40 % of it gets the clicks that bring it back, at about 60 % of the reference per click.',
    why:
      'This is the only tension measurement: friction while moving rises with tension and is not swamped by the gearbox. Differences up to 60 % can be the hand rather than the tension, so only joints below 40 % get clicks, rounded so they never go past 110 % of the reference. No click needed means well tensioned.',
    todo:
      'Keep clear of the hand. Nothing listed: go on to Run. Joints listed: press Tension again, ratchet them by the clicks shown, then calibrate and sweep once more.',
  },
  {
    key: 'again',
    title: 'Tension again',
    note: 'only the listed clicks',
    color: '#f59e0b',
    what: 'Guided tensioning opens at the ratchet step with the joints the sweep listed and the clicks each needs.',
    why:
      'Each click shifts the spool against the motor, so the limits and the sweep are only valid after a fresh calibration.',
    todo: 'Ratchet the listed spools by the clicks shown, press Done, then calibrate and sweep again.',
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

// Where each box sits on the chart (column, row): tensioning on the first row,
// the calibration loop on the second, Run at its end.
export const WORKFLOW_LAYOUT: Record<string, [col: number, row: number]> = {
  slack: [0, 0],
  ratchet: [1, 0],
  move: [2, 0],
  calibrate: [0, 1],
  measure: [1, 1],
  run: [2, 1],
  again: [1, 2],
}
// Arrows: from → to, with the condition on the arrow.
export const WORKFLOW_ARROWS: { from: string; to: string; label?: string; kind: 'next' | 'loop' | 'down' }[] = [
  { from: 'slack', to: 'ratchet', label: 'passed', kind: 'next' },
  { from: 'ratchet', to: 'move', kind: 'next' },
  { from: 'move', to: 'ratchet', label: 'joints short', kind: 'loop' },
  { from: 'move', to: 'calibrate', label: 'every joint passed', kind: 'down' },
  { from: 'calibrate', to: 'measure', kind: 'next' },
  { from: 'measure', to: 'run', label: 'no clicks left', kind: 'next' },
  { from: 'measure', to: 'again', label: 'clicks listed', kind: 'down' },
  { from: 'again', to: 'calibrate', label: 'calibrate and sweep again', kind: 'loop' },
]

// Steps that loop back, with what ends the loop.
export const WORKFLOW_LOOPS: { from: string; to: string; label: string }[] = [
  { from: 'move', to: 'ratchet', label: 'until every joint passes' },
  { from: 'again', to: 'calibrate', label: 'calibrate and sweep again' },
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

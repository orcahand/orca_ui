// The setup workflow the chart under the step tiles shows: one entry per step,
// in order, with what happens, why, and what to do. A v2.1 hand is tensioned
// in the guided loop (ratchet, move the fingers, round again); a v2.0 or
// unknown hand gets simple tensioning, the motors holding while you ratchet.

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

export interface WorkflowArrow {
  from: string
  to: string
  label?: string
  kind: 'next' | 'loop' | 'down'
}

export interface Workflow {
  steps: WorkflowStep[]
  // Where each box sits on the chart (column, row).
  layout: Record<string, [col: number, row: number]>
  arrows: WorkflowArrow[]
}

const SLACK = {
  key: 'slack',
  title: 'Slack test',
  note: 'hold each joint',
  color: '#64748b',
  what:
    'You hold one joint at a time so it cannot move while its motor winds each way at low current. Everything the spool turns before the tendons go taut is slack, shown in motor degrees and as ratchet clicks (at most 5 a round). Back tests the previous joint again, also from the end.',
  why:
    'A joint with more than half a turn of slack would unspool its tendon when calibrated, so calibration stays blocked until a test passes.',
}

const SLACK_FAILED =
  'Failed: tension that joint by hand — remove its top spool from the assembly and attach it back on with more pretension, rather than ratcheting that much — then run the slack test again.'

const CALIBRATE: WorkflowStep = {
  key: 'calibrate',
  title: 'Calibrate',
  note: 'automatic or manual',
  color: '#34d399',
  what:
    'Automatic: the motors drive every joint to both hard stops and record the motor positions there. Manual: torque off, you hold each joint on its stops and press Enter.',
  why: 'Tensioning changes the tendon lengths, so the limits are measured after it. The tension sweep runs between them.',
  todo:
    'Keep clear while the motors drive to the stops (automatic), or hold each joint on its stops and press Enter per step (manual). Then run the tension sweep.',
}

const MEASURE: WorkflowStep = {
  key: 'measure',
  title: 'Tension sweep',
  note: 'limit to limit, clicks counted',
  color: '#0ea5e9',
  what:
    'The joints of one kind are driven slowly from one calibrated limit to the other and back while each motor’s current is recorded. The friction along the travel is compared with the reference hand, and a joint well below it gets the clicks that bring it back, at most 3 a round.',
  why:
    'Friction while moving rises with tension and is not swamped by the gearbox, so this is the tension measurement. Some difference from the reference is the hand rather than the tendon, so only joints well below it get clicks. No clicks listed means well tensioned.',
  todo:
    'Keep clear of the hand. Nothing listed: go on to Run. Clicks listed: press Hold & ratchet in the sweep window, turn the marked spools by the clicks shown, release, then calibrate and sweep again.',
}

const RUN: WorkflowStep = {
  key: 'run',
  title: 'Run',
  note: 'the long test',
  color: '#94a3b8',
  what: 'The calibrated hand runs its joints through their ranges in a collision-free loop for a few minutes.',
  why: 'New tendons settle in the first minutes of motion; running before use keeps the calibration honest.',
  todo: 'Pick the minutes and the speed, start, and keep the hand clear. Done: the hand is ready to use.',
}

const CALIBRATION_ROW: Pick<Workflow, 'layout' | 'arrows'> = {
  layout: { calibrate: [0, 1], measure: [1, 1], run: [2, 1] },
  arrows: [
    { from: 'calibrate', to: 'measure', kind: 'next' },
    { from: 'measure', to: 'run', label: 'no clicks listed', kind: 'next' },
    { from: 'measure', to: 'calibrate', label: 'clicks listed: ratchet, calibrate again', kind: 'loop' },
  ],
}

export const GUIDED_WORKFLOW: Workflow = {
  steps: [
    {
      ...SLACK,
      todo: `Passed: On to tensioning opens the ratchet step with the clicks shown. ${SLACK_FAILED}`,
    },
    {
      key: 'ratchet',
      title: 'Ratchet',
      note: 'the listed spools, ~x clicks',
      color: '#f59e0b',
      what:
        'The finger motors turn a little counterclockwise and hold firmly, loading the bottom spools. The dialog marks the spools to ratchet, each with its clicks: from the slack test on the first round, then from the last finger check.',
      why:
        'The counts are rounded down and capped at 5, so every round stays a little loose: a click only ever adds tension, and the sweep after calibration counts the last ones.',
      todo:
        'Hulls off. Turn each marked top spool clockwise by the clicks shown, stop early if a tendon feels firm, then press Done. The fingers get checked next.',
    },
    {
      key: 'move',
      title: 'Move fingers',
      note: 'range check, finger by finger',
      color: '#22d3ee',
      what:
        'One finger at a time: torque off, you pose the finger like the model; Continue makes the motors hold that pose at low current. You then drive each highlighted joint by hand to both ends against the motors’ resistance, and the console scores how far each spool followed.',
      why: 'A spool that follows only part of the expected travel still has slack: the missing travel is what the next ratchet round takes up.',
      todo:
        'Pose the finger like the model, press Continue, drive each joint to both ends and hold each end for a moment, then Next. Joints short of their target go back to the ratchet; once every joint passes, calibrate.',
    },
    CALIBRATE,
    MEASURE,
    RUN,
  ],
  layout: { slack: [0, 0], ratchet: [1, 0], move: [2, 0], ...CALIBRATION_ROW.layout },
  arrows: [
    { from: 'slack', to: 'ratchet', label: 'passed', kind: 'next' },
    { from: 'ratchet', to: 'move', kind: 'next' },
    { from: 'move', to: 'ratchet', label: 'joints short', kind: 'loop' },
    { from: 'move', to: 'calibrate', label: 'every joint passed', kind: 'down' },
    ...CALIBRATION_ROW.arrows,
  ],
}

export const SIMPLE_WORKFLOW: Workflow = {
  steps: [
    {
      ...SLACK,
      todo: `Passed: On to tensioning holds the motors for simple tensioning, with the clicks shown listed. ${SLACK_FAILED}`,
    },
    {
      key: 'hold',
      title: 'Simple tensioning',
      note: 'motors hold, you ratchet',
      color: '#f59e0b',
      what:
        'Activating the current makes every finger motor turn a little counterclockwise and hold there, loading the bottom spools and keeping the tendons taut.',
      why:
        'With the motors holding, each ratchet click takes up slack at the top spool instead of pulling the finger. Nothing is scored here: the tension sweep after calibration says which spools still need clicks.',
      todo:
        'Hulls off. Ratchet each top spool clockwise until it clicks, aiming a little loose; Pull 15° more if the bottom spools are not loaded. Then Done — release motors, and calibrate.',
    },
    CALIBRATE,
    MEASURE,
    RUN,
  ],
  layout: { slack: [0, 0], hold: [1, 0], ...CALIBRATION_ROW.layout },
  arrows: [
    { from: 'slack', to: 'hold', label: 'passed', kind: 'next' },
    { from: 'hold', to: 'calibrate', label: 'motors released', kind: 'down' },
    ...CALIBRATION_ROW.arrows,
  ],
}

// The steps of visual calibration (orca_core experiments/visual_calibration/README.md),
// in the order they are done. Phase rig: the calibration object instead of the
// hand; the motor turns the plate through every stop twice, 1a for the camera
// (lens, tile poses), 1b for the rotation (camera pose, axis, stop angles).
// Phase hand: the hand on the same connector. For the assemblers (Measure joint ranges):
// connect the hand, calibrate its motor stops, mount it, measure (the rig's hand run),
// the results, write them to the hand's board. The study's hand steps are research extras.

import type { RigInfo, SessionKind } from './api'

export type Phase = 'rig' | 'hand'
export type StepId =
  | 'mount'
  | 'camera'
  | 'light'
  | 'lens'
  | 'rotation'
  | 'swap'
  | 'hand-board'
  | 'hand-calibrate'
  | 'hand-measure'
  | 'hand-results'
  | 'hand-write'
  | 'hand-capture'
  | 'hand-check'
  | 'hand-pose'
  | 'hand-control'
export type Art = 'mount' | 'camera' | 'light' | 'swap'

export interface StepDef {
  id: StepId
  phase: Phase
  title: string
  tag?: string // the step's name in orca_core (1a, 1b)
  copy: (rig: RigInfo | null) => string
  items?: (rig: RigInfo | null) => string[] // numbered, in the order they are done
  art?: Art
  live?: boolean // the camera image belongs on this step
  overlay?: boolean // the model overlay starts on (it can be switched on wherever the camera shows)
  sweep?: SessionKind // the motor turns the plate through the stops into a session of this kind
  solve?: boolean
  research?: boolean // a research extra of the hand study: shown only with --research-ui
}

const side0 = (rig: RigInfo | null) => `${rig?.side0_stop ?? 180}°`

export const STEPS: StepDef[] = [
  {
    id: 'mount',
    phase: 'rig',
    title: 'Mount the object',
    copy: (rig) =>
      `The calibration object goes on the hand connector: the two rods, then four radial M3. It bolts on any of four ways; all work, the calibration finds which way it sits${rig?.mounting ? ` (now: side 0 faces the camera at ${side0(rig)})` : ''}.`,
    art: 'mount',
    live: true,
    overlay: true,
  },
  {
    id: 'camera',
    phase: 'rig',
    title: 'Set up the cameras',
    copy: () =>
      'Both BRIOs on their sides: camera A above at the back, camera B on the side rail 45° down. The console owns them: the view here is its preview, every photo is taken by both. With the tower on the plate, Check cameras locks focus and exposure to the rig config and proves which camera is which (it refuses swapped or missing cameras). From here on, don’t touch the cameras.',
    art: 'camera',
    live: true,
  },
  {
    id: 'light',
    phase: 'rig',
    title: 'Light the tiles',
    copy: () => 'Even light, no glare on the tiles. Every tile the camera finds turns green.',
    art: 'light',
    live: true,
  },
  {
    id: 'lens',
    phase: 'rig',
    title: 'Calibrate the camera',
    tag: '1a',
    copy: () =>
      'The motor finds its hard stop, then turns the plate through every stop and a photo is taken at each. Solve finds the lens. Good is under 0.5 px.',
    live: true,
    sweep: 'camera',
    solve: true,
  },
  {
    id: 'rotation',
    phase: 'rig',
    title: 'Calibrate the rotation',
    tag: '1b',
    copy: () =>
      'The same sweep again. Solve finds where the camera is, the turning axis and the true angle of every stop, starting from the camera step. Then save it to the rig.',
    live: true,
    sweep: 'rotation',
    solve: true,
  },
  {
    id: 'hand-board',
    phase: 'hand',
    title: 'Connect the hand',
    copy: () => 'The hand to measure, connected to this console (the hand stays off the rig for now). The turntable’s board answers as a hand too; the console must take the hand’s board, never the turntable’s.',
    items: () => [
      'Plug in the hand’s board (USB and power).',
      'Pick it below. The turntable’s board is marked and cannot be picked.',
      'Wait until it shows connected, then go on.',
    ],
  },
  {
    id: 'hand-calibrate',
    phase: 'hand',
    title: 'Calibrate the motor stops',
    copy: () =>
      'orca_core’s normal calibration (Setup › Calibrate), unless the hand already has one from today: the motors drive every joint to its stops. Keep clear while it runs.',
  },
  {
    id: 'swap',
    phase: 'hand',
    title: 'Mount the hand',
    copy: () => 'The rig is calibrated; from here on the camera stays exactly where it is.',
    items: (rig) => [
      'Close Logi Tune (it rewrites the camera’s focus and exposure). Don’t touch the camera.',
      `Press “Park for the swap”: the plate turns to ${rig?.swap_angle ?? 180}° (the connector’s two rods side by side, facing you) and the torque is released. The plate then turns freely by hand; its angle is kept.`,
      'Take the tower off: undo the four radial M3, lift it straight up off the two rods.',
      `Put the hand on the same two rods, upright: at the parked ${rig?.swap_angle ?? 180}° the PALM FACES THE CAMERA (the way tile H faced), the back of the hand away. Right hand: seen from the camera the thumb is on the right; thumb on the left means it is the wrong way round (lift it off, turn it 180°). The overlay shows how it should sit. Then the four radial M3.`,
      'Route the hand’s cables with slack for the plate’s full 320°: turn the plate by hand from end to end once and check nothing pulls or catches.',
    ],
    art: 'swap',
    live: true,
    overlay: true,
  },
  {
    id: 'hand-pose',
    phase: 'hand',
    title: 'Estimate the hand pose (camera only)',
    research: true,
    copy: () =>
      'The hand’s mount and joint angles from the camera image alone: nothing needs to be connected, and the motor does not move. Drawn over the camera: the CAD hand (URDF) at the estimate, following the plate; the View panel adds the CAD hand at zero to compare.',
    items: (rig) => [
      'Auto-solve: estimates frame after frame (slower with the joints on); click again to stop. Move a finger by hand and the drawn hand follows.',
      'The table lists every joint with its uncertainty. Poor: this view can’t tell (seen palm-on, a bent finger and an over-stretched one look alike). The panel names a better plate angle for those.',
      `More views: turn the plate (by hand, or a move on the rig steps) to another angle, press “Keep view”, turn back. Every kept view joins the fit; the hand must not move in between. The plate angle comes from the turntable's read-back when it is connected, else ${rig?.swap_angle ?? 180}° is assumed.`,
      'Switch “solve joints” off to fit only the mount, with the joints from the connected hand (or zero).',
      'Freeze saves the frame and the estimate; Reset starts again from the CAD.',
    ],
    live: true,
    overlay: true,
  },
  {
    id: 'hand-measure',
    phase: 'hand',
    title: 'Measure joint ranges',
    copy: () =>
      'About 65 minutes: the hand takes 72 poses (the short block) and 25 more (the check), and at each pose the plate turns through its stops while both cameras photograph the hand. The hand and the plate never move together. Keep clear of the rig; E-STOP ends the run.',
    items: () => [
      'The hand on the rig, cables free for the plate’s full turn, the tower off.',
      'Measure: both cameras are checked first (focus, exposure, which is which); the run starts only if they pass.',
      'Keep orca-ui running: if it quits or crashes the run ends too (the next start cleans up anything left and turns the torque off); closing this page does not end it. Stop ends it now; it can’t be resumed here, Measure starts a new one.',
    ],
  },
  {
    id: 'hand-results',
    phase: 'hand',
    title: 'Results',
    copy: () =>
      'Per joint the range in force before and the measured one, and the hand’s accuracy on the 25-pose check before and after. The measured ranges are recorded in the hand’s joint_ranges.yaml on this computer and are in force here.',
  },
  {
    id: 'hand-write',
    phase: 'hand',
    title: 'Write to board',
    copy: () =>
      'The hand’s calibration and its measured ranges onto its own board, so they go with the hand. Read back to confirm.',
  },
  {
    id: 'hand-capture',
    phase: 'hand',
    title: 'Capture the hand',
    research: true,
    copy: () => 'One photo per stop, the same stops and the same approach (from the hard-stop side) as the rig calibration.',
    items: () => [
      'Put the hand at zero (every joint at 0°) and leave it there for the whole sweep.',
      'Run sweep: the cameras are checked first (focus and exposure set, which camera is which; the sweep stops if they can’t be), then the motor homes and turns through every stop, a photo from each camera at each.',
      'The photos stay in a hand session.',
    ],
    live: true,
    overlay: true,
    sweep: 'hand',
  },
  {
    id: 'hand-check',
    phase: 'hand',
    title: 'Check the overlay',
    research: true,
    copy: () => 'The hand’s CAD drawn where the calibrated rig puts it, posed by the hand’s joint angles. The automatic hand fit (its mount and joints from the photos) is not built yet: this is a check by eye.',
    items: () => [
      'Step through the stops with “Next stop”.',
      'Tower and forearm first: they should sit on the real parts at every stop.',
      'Off by the same amount at every stop: the hand sits on the connector another way round, or the CAD mount is off. Off differently at each stop: the hand rocks on the rods (not seated).',
      'Then the fingers at zero: one finger off on its own is that finger’s joint zero.',
      'Note what is off and at which stop.',
    ],
    live: true,
    overlay: true,
  },
  {
    id: 'hand-control',
    phase: 'hand',
    title: 'Accurate control (sandbox)',
    research: true,
    copy: () => 'Move the hand to the joint angles you want, through the hand study’s lookup table or straight through orca_core’s linear map, and see on the camera whether it really gets there. The CAD hand is drawn at the angles you ask for.',
    items: () => [
      'Torque on. The hand ramps slowly to every new target; leaving this step turns the torque off.',
      'Move the sliders: with “lookup table” on, the CAD outline and the real fingers should stay together.',
      'Touch tests: the hand opens, zeroes the fingertip sensors, then closes thumb onto the finger. Both pads must feel it. Run each finger with “std” and with “LUT” to compare.',
    ],
    live: true,
    overlay: true,
  },
]

/** The steps without the research extras: what is on offer unless the console runs with --research-ui. */
export const ASSEMBLER_STEPS: StepDef[] = STEPS.filter((s) => !s.research)

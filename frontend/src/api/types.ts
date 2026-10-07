// The backend contract. Mirrors orca_ui/api/schemas.py + the topic payloads
// assembled in orca_ui/hand/service.py and orca_ui/hand/telemetry.py.

export type Finger = 'thumb' | 'index' | 'middle' | 'ring' | 'pinky'
export const FINGERS: Finger[] = ['thumb', 'index', 'middle', 'ring', 'pinky']

export type Vec3 = [number, number, number]

export type HandState =
  | 'disconnected'
  | 'detecting'
  | 'connecting'
  | 'connected'
  | 'degraded'
  | 'reconnecting'
  | 'maintenance'

export interface Capabilities {
  motors: boolean
  tactile: boolean
  encoders: boolean
  feedback_loop: boolean
  declared: Record<string, boolean>
  degraded: boolean
}

export interface StatusSnapshot {
  state: HandState
  capabilities: Capabilities | null
  torque_enabled: boolean
  message: string
  ports: Record<string, string | null>
  since: number
  // Hand config currently in force. Not fixed for the session: unless a model
  // was pinned on the command line, the backend re-derives it from whatever
  // is plugged in, so a swapped hand shows up as a change here.
  model: string
  side: string
  // False while the model is still detection's to revise, true once the
  // command line or the picker named one.
  model_pinned: boolean
  // True while someone has taken the hardware back: the connect ladder is
  // suspended, so `disconnected` is a resting state rather than a search.
  released: boolean
  // Device path of the board this console is pinned to, or null for "first
  // board to answer". Pinned means the backend never opens another board's
  // ports — the way two consoles on one machine each keep to their own hand.
  board_pinned: string | null
  // Device classes the config declares that this session did not get, and
  // whether the backend is still probing for them. It gives up after a few
  // attempts, so the UI offers an explicit rescan rather than implying it is
  // still looking.
  missing?: string[]
  // Of those, the ones whose port answered while the device did not, so a
  // rescan re-attempts the connection rather than looking for a port.
  refused?: string[]
  rescanning?: boolean
  // Bare motor mode: loose motors brought up from a bus scan, with no hand
  // behind them. Joints are one-to-one stand-ins for motors, so anything that
  // poses a hand or commands a joint is hidden.
  bare?: boolean
}

export interface ModelEntry {
  name: string
  version: string // '' for a model outside orca_core's bundle
  side: 'left' | 'right'
  tactile: boolean
  encoders: boolean
  config_path: string
  // False for a --config path: shown as current, but it has no model name to
  // be selected back by.
  selectable: boolean
}

export interface ModelsInfo {
  models: ModelEntry[]
  selected: string
  pinned: boolean
  // Detection needs a bus to ask — mock mode has none.
  auto_available: boolean
  config_path: string
}

// One selectable board from GET /api/boards: an ORCA controller board (both
// CDCs grouped by the identity they report) or a legacy motor adapter.
export interface BoardEntry {
  device: string // the pin key: motor CDC, or the adapter path
  kind: 'oh_board' | 'motor_adapter'
  side: 'left' | 'right' | null
  hand_id: string | null
  // Model the board's provisioned config declares; null when it doesn't.
  model_name: string | null
  ports: string[]
  // Held open by some *other* process (e.g. a second console) — silent under
  // probing, so side/identity are unknown.
  busy: boolean
  // Held by this console's own live session.
  held_by_console: boolean
}

export interface BoardsInfo {
  boards: BoardEntry[]
  // Pinned device path, or null = first board to answer.
  selected: string | null
  // False in mock mode: no serial ports to scan or pin.
  available: boolean
}

export interface JointInfo {
  id: string
  // Motor driving this joint, or null when the config maps none.
  motor_id: number | null
  rom: [number, number] // degrees
  neutral: number
  encoder_backed: boolean
  // null: unknown (no session yet) or not an encoder joint. false: the joint
  // has an encoder but no calibration anchor — raw counts can't be decoded.
  encoder_calibrated: boolean | null
  // true: the feedback loop closes on this joint. false: the loop skipped it
  // at connect (incomplete motor/encoder calibration) — it runs open-loop
  // until recalibrated. null: no loop at this tier, or the joint has no
  // encoder to close on.
  loop_controlled: boolean | null
}

export interface CalibrationInfo {
  // Motor limits + ratios recorded. null when no motor session.
  motors: boolean | null
  // Motors calibrated AND every encoder-backed joint anchored.
  joint_feedback: boolean | null
  // Encoder-backed joints with no anchor — they run open-loop.
  missing_anchors: string[]
  // Set when recalibrating would capture the missing anchors.
  hint: string | null
}

// Who owns the joint-target channel. TELEOP is reserved for orca_teleop.
export type ControlSource = 'manual' | 'operation' | 'teleop'

export interface JointGains {
  kp: number
  ki: number
  correction_max_deg: number
}

export interface ControlState {
  torque_enabled: boolean
  max_current: number
  // The one gain set every loop joint shares, or null when they differ.
  gains: JointGains | null
  // Live gains per loop-controlled joint, read back from the controller.
  joint_gains: Record<string, JointGains>
  // What connect() installed from config.yaml — what Reset returns to.
  config_gains: Record<string, JointGains>
  tactile_mode: TactileMode
  control_source: ControlSource
  // Human-readable owner label, e.g. "manual", "replay", or the op kind.
  control_owner: string
  // Raw motor-space control armed: loop writes paused, joint targets 409.
  direct_motor_mode: boolean
  // Which stream the 3D model follows. "auto" tracks the torque state:
  // motor estimate while limp (polled), commanded targets once torqued (no
  // polling, so reads stop competing with commands for the bus).
  pose_source: PoseSource
  // What "auto" resolved to right now; equals pose_source when pinned.
  effective_pose_source: 'estimate' | 'target'
}

// Control-table facts for a model a bench knows how to drive. `source` says
// where the numbers came from, because a wrong one writes to a register the
// motor may not have.
export interface MotorModelInfo {
  key: string
  label: string
  family: string
  model_numbers: number[]
  has_current_control: boolean
  current_scale_ma: number | null
  max_current_ma: number | null
  source: string
  verifiable: boolean
}

export interface DirectMotorInfo {
  id: number
  joint: string
  position: number // radians
  // Present draw and case temperature where the family reports them. On a
  // bench these are how a stall reads: the target is missed either way, and
  // only the current says whether the motor is still pushing.
  // What the operator declared is plugged in here, and whether the servo's
  // own reported model number agrees with it.
  nickname?: string
  model?: MotorModelInfo
  reported_model_number?: number | null
  identified?: MotorModelInfo | null
  mismatch?: boolean
  // The travel an operator found by hand, in radians, once recorded.
  range_rad?: [number, number] | null
  // Points recorded by hand. One is a place to hold, two or more is a cycle.
  points?: number[] | null
  playing?: boolean
  current_ma?: number | null
  temp_c?: number | null
  hw_error: number | null
  hw_error_flags: string[] | null
}

export interface DirectMotorSnapshot {
  direct_mode: boolean
  // null in bare motor mode: the cap exists so a slider cannot yank a tendon,
  // and a loose motor on a bench has none.
  max_step_rad: number | null
  // The travel this motor family can reach, in radians. null for a family with
  // no single-turn limit.
  span_rad?: [number, number] | null
  motors: DirectMotorInfo[]
}

// Which orca_core the backend imported. `development` is true for a local
// checkout or a git branch — i.e. not a released build.
export interface CoreSourceInfo {
  version: string
  kind: 'released' | 'local' | 'git' | 'unknown'
  branch: string | null
  dirty: boolean
  development: boolean
  summary: string
}

export interface HandInfo {
  model_name: string
  side: 'left' | 'right'
  mock: boolean
  joints: JointInfo[]
  calibration: CalibrationInfo
  control: ControlState
  core?: CoreSourceInfo
  // False on a motor family with no reboot instruction; the reboot control hides.
  reboot_supported?: boolean
  finger_to_sensor_id?: Record<Finger, number>
  tactile?: { active_sensors: Finger[]; num_taxels: Record<Finger, number> }
}

export type TactileMode = 'resultant' | 'taxels' | 'combined'

export interface TaxelGeometry {
  [finger: string]: {
    frame: string
    positions: [number, number, number][] // mm, fingertip-local
    source: string
  }
}

export interface ModelMetadata {
  side: 'left' | 'right'
  urdf_url: string
  mesh_base_url: string
  manifest: { joints: string[]; [key: string]: unknown }
}

// ----- operations (orca_ui/hand/operations/) --------------------------------

export type OperationState =
  | 'starting'
  | 'running'
  | 'paused'
  | 'awaiting_input'
  | 'stopping'
  | 'done'
  | 'error'

export interface OperationSnapshot {
  kind: string
  run_id: string
  state: OperationState
  phase: string | null
  detail: string | null
  progress: number | null // 0..1 or null when indeterminate
  params: Record<string, unknown>
  awaiting: { prompt: string; options: string[] } | null
  // Op-specific structured state for rich panels (e.g. the motor-chain
  // grid). Shape is per-kind; see MotorChainExtra.
  extra: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null
  started_at: number
}

// ----- configure_chain operation extra (orca_ui/hand/operations/chain.py) ----

export interface MotorChainSlot {
  id: number
  model: string // e.g. XC330 (finger) / XC430 (wrist)
  role: 'finger' | 'wrist'
  state: 'pending' | 'expected' | 'configured' | 'invalid' | 'reset'
}

export interface MotorChainExtra {
  mode: 'configure' | 'reset'
  motor_type: string
  target_baud: number
  chain: MotorChainSlot[]
  resets: number[]
}

export interface OperationLogLine {
  seq: number
  t: number
  line: string
}

// CUMULATIVE payload (the hub coalesces latest-wins, so every publish carries
// the run's whole bounded buffer). Merge lines with seq > last seen.
export interface OperationLogPayload {
  run_id: string | null
  next_seq: number
  lines: OperationLogLine[]
}

// ----- teleoperation (orca_ui/hand/teleop/) ----------------------------------

export type TeleopSourceId = 'mediapipe' | 'manus' | 'avp' | 'synthetic'

// 'idle' means no session; the backend always publishes a full snapshot.
export type TeleopSessionState =
  | 'idle'
  | 'starting' // child spawning / waiting for its hello
  | 'preview' // targets flow to the 3D ghost only, hand untouched
  | 'engaged' // arbiter owned as TELEOP; sub-flags ramping/tracking
  | 'error' // sticky until the next start/stop

export interface TeleopSnapshot {
  state: TeleopSessionState
  source: TeleopSourceId | null
  session_id: string | null
  mode: 'managed' | 'external' | null
  engaged: boolean
  ramping: boolean
  tracking: 'ok' | 'lost'
  calibrating: { done: boolean; frames: number; needed: number } | null
  child: {
    mode: string | null
    pid: number | null
    connected: boolean
  } | null
  stats: {
    ingress_fps?: number
    retarget_ms?: number
    target_hz: number | null
    last_target_age_ms: number | null
  }
  config: Record<string, unknown>
  availability: { available: boolean; detail: string | null }
  // Last automatic transition, e.g. "auto-disengaged — tracking lost for
  // 10s". Cleared on the next engage/stop/start.
  notice: string | null
  error: string | null
}

export interface TeleopSourceAvailability {
  installed: boolean
  ready: boolean
  detail: string | null
}

export interface TeleopCamera {
  index: number
  name: string | null // host camera name (macOS), e.g. "FaceTime HD Camera"
  width: number | null
  height: number | null
  // False: the OS knows this camera but the probe couldn't open it — e.g.
  // an iPhone Continuity Camera that's asleep. Selectable anyway.
  available: boolean
}

export interface TeleopSourcesInfo {
  runner: { available: boolean; detail: string | null }
  sources: Record<TeleopSourceId, TeleopSourceAvailability>
  cameras: TeleopCamera[] | null // null = never scanned
  default_camera_index: number | null // built-in preferred over Continuity
}

// ----- library: poses / trajectories / demos (orca_ui/library.py) -----------

export interface PoseEntry {
  name: string
  builtin: boolean
  // Built-ins ship as ROM-fraction placeholders until tuned on the real hand.
  placeholder: boolean
  saved_at?: string | null
}

export interface TrajectoryEntry {
  name: string
  type: 'continuous' | 'discrete_waypoints' | 'motor_waypoints' | null
  frames: number
  frequency_hz: number | null
  duration_s: number | null
  created_at: string | null
}

export interface DemoEntry {
  name: string
  poses: number
  source: 'orca_core' | 'orca_ui'
}

// Mirrors the backend library's NAME_RE (orca_ui/library.py): no path
// traversal, 1-64 chars of letters/digits/_/-.
export const LIBRARY_NAME_RE = /^[a-zA-Z0-9_-]{1,64}$/

export interface PortInfo {
  device: string
  description: string
  kind: string | null
}

// ----- motor faults (motors.faults topic, orca_ui/hand/faults.py) -----------

// Command adherence for the joint a motor drives: sustained target-vs-actual
// deviation past a grace window counts as "not following".
export interface MotorTracking {
  following: boolean
  deviation_deg: number | null
  stall_s: number // current stall duration; 0 while following
  stalls: number // stall events this session
  stalled_total_s: number // cumulative not-following time this session
}

// A latched Hardware Error Status, classified by what to do about it. Every
// latched bit disables the motor identically (it answers the bus and ACKs
// torque enable, but never energizes) — `kind` is what separates a fault you
// wait out from one you go and fix.
export type HwErrorKind = 'thermal' | 'power' | 'load' | 'encoder' | 'unknown'

export interface HwErrorInfo {
  flags: string[]
  kind: HwErrorKind
  disabled: boolean // always true today; the motor will not move until reboot
  needs_cooling: boolean // separate from kind: a motor can latch both
  temperature_c: number | null
  headline: string
  advice: string
  disabled_note: string
}

export interface MotorFaultEntry {
  joint: string | null
  errors: number // failed bus transactions this session
  overloads: number // overload reboots this session
  last_error: string | null
  last_error_age_s: number | null
  tracking: MotorTracking | null
  hw_error_flags?: string[]
  // null when nothing is latched.
  hw_error?: HwErrorInfo | null
  // Did this motor answer the last error sweep? null before the first one:
  // "not asked yet" is not "not answering".
  answering?: boolean | null
}

// The servo's own position-PID and feedforward gains (X-series registers
// 80-91). Distinct from the host outer-loop PI in the Control Loop panel:
// these close the loop inside the motor. null when the family cannot report
// them.
export interface ServoGains {
  kp: number | null
  ki: number | null
  kd: number | null
  ff_1st: number | null
  ff_2nd: number | null
}

export type ServoGainsMap = Record<string, ServoGains | null>

// Trajectory limits the servo shapes its own motion with. 0 disables a limit.
// Non-zero values rate-limit streamed targets too, not just point-to-point
// moves — a safety property for teleop, an unwanted lag inside a tuned loop.
export interface ServoProfile {
  velocity_rad_s: number | null
  acceleration_rad_s2: number | null
}

export type ServoProfileMap = Record<string, ServoProfile | null>

export type PoseSource = 'auto' | 'estimate' | 'target'

export interface MotorsFaults {
  motors: Record<string, MotorFaultEntry>
  bus: {
    errors: number
    last_error: string | null
    last_error_age_s: number | null
  }
}

// ----- WS topics ------------------------------------------------------------

export const TOPICS = {
  status: 'status',
  controlState: 'control.state',
  error: 'error',
  operationState: 'operation.state',
  operationLog: 'operation.log',
  tactileForces: 'tactile.forces',
  tactileTaxels: 'tactile.taxels',
  jointsMeasured: 'joints.measured',
  jointsEstimate: 'joints.estimate',
  jointsTarget: 'joints.target',
  jointsCorrection: 'joints.correction',
  motorsTelemetry: 'motors.telemetry',
  motorsFaults: 'motors.faults',
  stats: 'stats',
  sensorsHealth: 'sensors.health',
  teleopState: 'teleop.state',
  teleopTargets: 'teleop.targets',
  teleopLog: 'teleop.log',
  teleopPreview: 'teleop.preview',
} as const

export interface ServerMessage {
  type: string
  seq?: number
  t?: number
  data: Record<string, unknown>
}

// ----- sensors.health (orca_ui/hand/telemetry.py SensorHealthMonitor) -------

export type EncoderVerdict =
  | 'live'
  | 'parity'
  | 'chip error'
  | 'no encoder'
  | 'no frames'

export interface EncoderJointHealth {
  slot: number
  deg: number | null // raw-decoded chip angle (uncalibrated frame)
  verdict: EncoderVerdict
  reason: string
}

export interface SensingLinkHealth {
  connected: boolean
  port_dead: boolean
  port_error: string | null
  resyncs: number
  bad_lrc: number
}

// 1 Hz electrical bring-up payload; null sections = capability absent.
export interface SensorsHealth {
  encoders: {
    present: boolean
    hz: number
    error_byte: number | null
    fresh_ms?: number | null
    joints: Record<string, EncoderJointHealth>
    live: number
    total: number
    // Joints whose measured stream is currently distrusted (joint ->
    // "verdict: reason"): the backend drops them from joints.measured and
    // everything falls back to the motor estimate until the sensor reads
    // clean for restore_after_s consecutive seconds.
    suppressed?: Record<string, string>
    restore_after_s?: number
  } | null
  tactile: {
    present: boolean
    hz: number
    stream_rearms: number | null
    fingers: Record<string, { connected: boolean; taxels: number }>
  } | null
  links: Record<string, SensingLinkHealth>
}

export interface Stats {
  loop: Record<string, number | boolean> | null
  tactile: {
    frames_ok: number
    frames_bad_payload_size: number
    frames_bad_payload: number
    last_error_code: number
    stream_rearms: number
  } | null
  encoder: { frames_ok: number; last_freshness_ms: number } | null
}

// Something the operator has to act on, surfaced on the run's `extra` while
// it goes and kept on its result. One entry per joint per kind.
export interface CalibrationProblem {
  kind: 'no_motion' | 'travel' | 'rejected' | 'timeout' | 'faulted'
  joint: string
  severity: 'error' | 'warn'
  headline: string
  advice: string
  motor?: number
  direction?: string
  moved_deg?: number
  travel_deg?: number
  expected_deg?: number
  flags?: string[]
  temperature_c?: number | null
  fault_kind?: string
  needs_cooling?: boolean
}

// ----- calibration history --------------------------------------------------

// One raw progress event from a calibration run (t = epoch seconds). The
// magnet counts sampled at the two hardstops ride on the measured_rom_*
// events so successive runs can be compared for encoder-magnet drift.
export interface CalibrationEvent {
  t: number
  event: string
  joint?: string
  anchor_count?: number
  anchor_angle_deg?: number
  flex_count?: number
  extend_count?: number
  rom?: [number, number]
  span_deg?: number
  deviation_deg?: number
  ratio?: number
  // limit_recorded: motor-shaft position (rad) sampled at one hardstop.
  motor?: number
  limit?: number
  bound?: 'lower' | 'upper'
  error?: string
  steps?: number
  joints?: Record<string, string> | string[]
  index?: number
  total?: number
}

// ----- joint usage stats ----------------------------------------------------

// Full stored trajectory (GET /api/trajectories/{name}) — the waypoint
// editor's working copy. Continuous recordings carry `angles`, waypoint
// recordings `waypoints`; rows follow metadata.joint_ids order.
export interface TrajectoryData {
  metadata: {
    type: string
    joint_ids?: string[]
    hand_type?: string | null
    created_at?: string
    edited_at?: string
    sampling_frequency_hz?: number
  }
  waypoints?: number[][]
  angles?: number[][]
}


// What a servo tunable accepts, and the ceiling that actually binds. The two
// differ by orders of magnitude: a speed register stores values far faster
// than the motor turns and never objects, so only the per-motor ceiling tells
// an operator what asking for a number will do.
export interface ServoLimitEntry {
  min: number
  max: number | null
  unit: string
  zero_means: string
  register_width_only?: boolean
  ceiling_source?: string
}

export interface ServoLimits {
  tunables?: Record<string, ServoLimitEntry>
  per_motor?: Record<string, { velocity_rad_s: number; acceleration_rad_s2: number }>
}


// ----- configuration registers (bare bench) --------------------------------
// Rendered from what the connected family declares, never from a list here:
// a family without a setting sends no row for it, and one that gains a
// setting needs no change in the browser.

export interface MotorConfigRegister {
  key: string
  label: string
  address: number
  size: number
  eeprom: boolean
  unit: string
  min: number | null
  max: number | null
  // Raw value -> meaning. A baud index is 9600 on one family and 1 000 000
  // on the other, so the raw number must never be shown on its own.
  choices: Record<string, string> | null
  // Changing this moves the motor on the bus.
  reidentifies: boolean
  note: string
}

export interface MotorConfigSchema {
  motor_type: string | null
  // Ids a bench re-scan will actually find. Narrower than the id register
  // allows: offering one outside this writes fine and then loses the motor.
  id_range: [number, number]
  registers: MotorConfigRegister[]
}

export interface MotorConfigValues {
  id: number
  values: Record<string, number | null>
}

export interface MotorConfigWriteResult {
  id: number
  key: string
  requested: number
  actual: number | null
  applied: boolean
  rescanned: boolean
}

export interface BusBaudInfo {
  current: number | null
  rates: number[]
}

export interface BusBaudResult {
  requested: number
  changed: number[]
  failed: number[]
  rescanned: boolean
}

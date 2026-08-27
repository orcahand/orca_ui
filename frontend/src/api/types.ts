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

export interface JointInfo {
  id: string
  // Motor driving this joint, or null when the config maps none.
  motor_id: number | null
  rom: [number, number] // degrees
  // Encoder-measured travel from the calibration sweep (anchor frame), the
  // measured-minus-config span delta in degrees, and the ROM the joint↔motor
  // map currently runs in. All null without a measured sweep / session.
  rom_measured?: [number, number] | null
  rom_delta?: number | null
  rom_effective?: [number, number] | null
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
  // Calibration is missing or incomplete: nothing recorded at all, or motors
  // recorded but encoder anchors missing. What the "calibrate" prompts gate on.
  needs_calibration: boolean
  // Set whenever needs_calibration is — the sentence to show the user.
  hint: string | null
  // config.yaml defaults for the sweep's hardstop current (mA) — what a
  // per-run calibration_current override replaces.
  calibration_current?: number | null
  wrist_calibration_current?: number | null
}

// Result of a manual joint-sensor calibration (POST /api/joints/calibrate).
export interface JointCalibrateResult {
  joint: string
  angle_deg: number
  anchor_count: number
  // The running feedback loop picked the new anchor up live; false means the
  // joint engages closed-loop on the next reconnect.
  loop_updated: boolean
  measured_deg: number | null
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
  // config.yaml's ceiling — what the Motor Control "default" button
  // restores. Unchanged by set_max_current (mirrors config_gains).
  config_max_current: number
  // Lowest ceiling orca_core accepts (the hand's calibration current); a
  // write below it is a 400, so the control stops here.
  max_current_floor: number
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
}

export interface DirectMotorInfo {
  id: number
  joint: string
  position: number // radians
  hw_error: number | null
  hw_error_flags: string[] | null
}

export interface DirectMotorSnapshot {
  direct_mode: boolean
  max_step_rad: number
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

export type RomFrame = 'anchor' | 'centered'

export interface HandInfo {
  model_name: string
  // Which ROM frame the joint↔motor map runs in; null without a session.
  rom_frame?: RomFrame | null
  side: 'left' | 'right'
  mock: boolean
  joints: JointInfo[]
  calibration: CalibrationInfo
  control: ControlState
  core?: CoreSourceInfo
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

// ----- stress_test operation extra (orca_ui/hand/operations/stress.py) -------

export interface StressJointReach {
  id: string
  // Commanded extremes in degrees (config ROM, less the safety margin).
  target: [number, number]
  commanded_span_deg: number
  // Settled position at each extreme, null until both ends have been
  // sampled — or for the whole run on a hand with no joint-angle source.
  reached: [number, number] | null
  span_deg: number | null
  // Commanded travel minus achieved travel: grows as a tendon stretches.
  span_shortfall_deg: number | null
  worst_shortfall_deg: number | null
}

export interface StressTestExtra {
  cycle: number
  cycles: number
  loop: boolean
  // False when the hand has no joint-angle source — the run still happens,
  // it just cannot report how far the joints got.
  measured: boolean
  joints: StressJointReach[]
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
  runner: {
    available: boolean
    detail: string | null
    // Machine-readable cause, so the UI can offer the right fix instead of
    // parsing `detail`. 'no_streamer_entrypoint' = a checkout on a branch
    // that predates the console's streamer script.
    reason?:
      | 'ok'
      | 'no_checkout'
      | 'no_pyproject'
      | 'no_streamer_entrypoint'
      | 'no_uv'
    default_install_path?: string
  }
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

export interface MotorFaultEntry {
  joint: string | null
  errors: number // failed bus transactions this session
  overloads: number // overload reboots this session
  last_error: string | null
  last_error_age_s: number | null
  tracking: MotorTracking | null
}

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
  teleopInstall: 'teleop.install',
  teleopInstallLog: 'teleop.install.log',
} as const

// Fetching + building the orca_teleop checkout. Its own log run_id space, so
// install output is never cleared by a teleop session starting.
export interface TeleopInstallTarget {
  path: string
  state: 'empty' | 'existing_checkout' | 'occupied'
  detail: string
}

export interface TeleopInstallState {
  running: boolean
  phase: string | null
  target: string | TeleopInstallTarget | null
  error: string | null
  finished: boolean
  ok: boolean | null
  default_path: string
  repo: string
  branch: string
}

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

// The CURRENT sensor frame per joint: what the live decode uses. Lets the
// browser turn a run's raw hardstop magnet counts into today's angles
// (angle = polarity × wrap(count − anchor_count) × LSB + anchor_angle_deg).
export interface SensorFrameEntry {
  anchor_count: number
  polarity: number
  anchor_angle_deg: number
}

// One line of calibration_history.jsonl (stored next to calibration.yaml).
export interface CalibrationRun {
  started_at: string
  finished_at: string
  joints: string[] | null
  force_wrist: boolean
  anchor_pass: boolean
  completed: boolean
  error: string | null
  simulated?: boolean
  events: CalibrationEvent[]
}

// ----- joint usage stats ----------------------------------------------------

// Lifetime usage counters for one joint, persisted in joint_usage.json next
// to calibration.yaml. hist is a time-weighted histogram (seconds per bin)
// over the joint's config ROM.
export interface JointUsage {
  rom: [number, number]
  travel_deg: number
  moving_s: number
  observed_s: number
  hist: number[]
  min_deg: number | null
  max_deg: number | null
  reversals: number
  max_speed_dps: number
  first_seen: string | null
  last_active: string | null
}

// One sensor-health state transition (encoder verdict change, tactile
// finger connect/disconnect, sensing-link or motor-bus up/down).
export interface UsageHealthEvent {
  t: string
  subject: string
  from: string | null
  to: string
}

export interface UsageHealth {
  observed_s: number
  down_s: Record<string, number>
  events: UsageHealthEvent[]
  events_dropped: number
}

// One user-managed stats session; the last one in the list is live.
export interface UsageSession {
  id: string
  label: string | null
  started_at: string
  ended_at: string | null
  joints: Record<string, JointUsage>
  health: UsageHealth
}

export interface UsageSnapshot {
  path: string
  created_at: string | null
  updated_at: string | null
  bins: number
  current_id: string | null
  sessions: UsageSession[]
}

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

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
  // Calibration is missing or incomplete: nothing recorded at all, or motors
  // recorded but encoder anchors missing. What the "calibrate" prompts gate on.
  needs_calibration: boolean
  // Set whenever needs_calibration is — the sentence to show the user.
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

export interface HandInfo {
  model_name: string
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
  type: 'continuous' | 'discrete_waypoints' | null
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
  stats: 'stats',
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

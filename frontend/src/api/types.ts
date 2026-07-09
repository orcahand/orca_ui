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
}

export interface JointInfo {
  id: string
  rom: [number, number] // degrees
  neutral: number
  encoder_backed: boolean
  // null: unknown (no session yet) or not an encoder joint. false: the joint
  // has an encoder but no calibration anchor — raw counts can't be decoded.
  encoder_calibrated: boolean | null
}

// Who owns the joint-target channel. TELEOP is reserved for orca_teleop.
export type ControlSource = 'manual' | 'operation' | 'teleop'

export interface ControlState {
  torque_enabled: boolean
  max_current: number
  gains: { kp: number; ki: number; correction_max_deg: number }
  tactile_mode: TactileMode
  control_source: ControlSource
  // Human-readable owner label, e.g. "manual", "replay", or the op kind.
  control_owner: string
}

export interface HandInfo {
  model_name: string
  side: 'left' | 'right'
  mock: boolean
  joints: JointInfo[]
  control: ControlState
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

export interface JointCalibrationEntry {
  sign: 1 | -1
  offset_deg: number
  verified: boolean
  evidence: string
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
} as const

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

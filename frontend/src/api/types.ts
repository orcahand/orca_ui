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
  result: Record<string, unknown> | null
  error: string | null
  started_at: number
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

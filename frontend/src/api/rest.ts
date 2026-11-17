// Thin fetch wrappers over the REST API. Errors carry the backend's detail.

import type {
  AppEntry,
  AppId,
  AppSnapshot,
  BoardsInfo,
  BusBaudInfo,
  BusBaudResult,
  ChangelogDoc,
  ControlState,
  DemoEntry,
  DirectMotorSnapshot,
  HandInfo,
  HandStoreInfo,
  ModelMetadata,
  ModelsInfo,
  MotorConfigSchema,
  MotorConfigValues,
  MotorConfigWriteResult,
  MotorModelInfo,
  OperationLogPayload,
  OperationSnapshot,
  PortInfo,
  PoseEntry,
  PoseSource,
  ServoGains,
  ServoGainsMap,
  ServoLimits,
  ServoProfile,
  ServoProfileMap,
  Stats,
  StatusSnapshot,
  TactileMode,
  TaxelGeometry,
  TensionSweeps,
  TrajectoryData,
  TrajectoryEntry,
  TravelBaselines,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' })
}

export const api = {
  status: () => request<StatusSnapshot>('/api/status'),
  handInfo: () => request<HandInfo>('/api/hand/info'),
  stats: () => request<Stats>('/api/stats'),
  changelog: () => request<ChangelogDoc>('/api/changelog'),
  changelogSeen: (dismissed: boolean) =>
    post<ChangelogDoc>('/api/changelog/seen', { dismissed }),
  ports: () => request<PortInfo[]>('/api/ports'),
  taxelGeometry: () => request<TaxelGeometry>('/api/tactile/geometry'),
  // Re-arm the probes for declared hardware this session did not get. Keeps
  // the session up, unlike reconnect.
  rescan: () =>
    post<{ ok: boolean; status: StatusSnapshot }>('/api/rescan'),
  reconnect: () => post<{ status: StatusSnapshot }>('/api/reconnect'),
  // Closes the session and holds the ports free; only reconnect() lifts it.
  disconnect: () => post<{ status: StatusSnapshot }>('/api/disconnect'),

  // Scans free serial ports on the backend, so it can take a moment.
  boards: () => request<BoardsInfo>('/api/boards'),
  // device null hands the choice back to "first board to answer".
  selectBoard: (device: string | null) =>
    post<BoardsInfo>('/api/board/select', { device }),
  // Runs the connected hand as this version for the session; null = the board's.
  setHardwareVersion: (version: number | null) =>
    post<StatusSnapshot>('/api/hardware_version', { version }),
  setHandNickname: (nickname: string | null) =>
    post<HandStoreInfo>('/api/hand/nickname', { nickname }),
  // Both reconnect the hand on the calibration they put in force.
  restorePreviousCalibration: () =>
    post<{ written: string }>('/api/hand/calibration/restore_previous'),
  boardCalibration: (choice: 'use_board' | 'keep_session' | 'keep_until_change') =>
    post<{ written: string | null }>('/api/hand/calibration/board', { choice }),
  dismissLegacyFiles: () => post<HandStoreInfo>('/api/hand/legacy_files/dismiss'),
  // Clears a latched hardware error. The motor's torque is restored if the hand has torque.
  rebootMotor: (id: number) =>
    post<{
      motor: number
      joint: string | null
      // null: the motor did not answer the read-back after the reboot.
      cleared: boolean | null
      read_back: boolean
      hw_error_flags: string[] | null
    }>(`/api/motors/${id}/reboot`),

  // Read straight off the motors: gains are RAM and a power cycle clears
  // them, so what was last typed is not evidence of what they hold.
  servoGains: () =>
    // gain_max is the family's register width, reported rather than assumed:
    // X-series gains are two bytes, HLS gains one.
    request<{ gains: ServoGainsMap; gain_max: number | null }>(
      '/api/motors/gains',
    ),
  // Omitted fields are left alone on the motor.
  setServoGains: (id: number, gains: Partial<ServoGains>) =>
    post<{ gains: ServoGainsMap }>(`/api/motors/${id}/gains`, gains),

  servoProfile: () =>
    request<{ profile: ServoProfileMap; limits?: ServoLimits }>(
      '/api/motors/profile',
    ),
  setServoProfile: (id: number, profile: Partial<ServoProfile>) =>
    post<{ profile: ServoProfileMap }>(`/api/motors/${id}/profile`, profile),

  motorConfigSchema: () =>
    request<MotorConfigSchema>('/api/motors/config/schema'),
  motorConfigTakenIds: () =>
    request<{ ids: number[] }>('/api/motors/config/taken-ids'),
  motorConfigRead: (id: number) =>
    request<MotorConfigValues>(`/api/motors/${id}/config`),
  motorConfigWrite: (id: number, key: string, value: number) =>
    post<MotorConfigWriteResult>(`/api/motors/${id}/config`, { key, value }),
  busBaud: () => request<BusBaudInfo>('/api/motors/bus/baud'),
  setBusBaud: (baud_rate: number) =>
    post<BusBaudResult>('/api/motors/bus/baud', { baud_rate }),

  models: () => request<ModelsInfo>('/api/models'),
  // name null hands the choice back to hardware detection.
  selectModel: (name: string | null, version?: string | null) =>
    post<ModelsInfo>('/api/model/select', { name, version: version ?? null }),

  sweeps: () => request<TensionSweeps>('/api/sweeps'),
  sweepReference: (name: string | null) =>
    post<{ reference: string | null }>('/api/sweeps/reference', { name }),
  baselines: () => request<TravelBaselines>('/api/baselines'),
  operation: () =>
    request<{ operation: OperationSnapshot | null }>('/api/operation'),
  operationLog: () => request<OperationLogPayload>('/api/operation/log'),
  operationStart: (kind: string, params: Record<string, unknown> = {}) =>
    post<{ operation: OperationSnapshot }>(`/api/operation/${kind}/start`, {
      params,
    }),
  operationStop: () =>
    post<{ ok: boolean; stopped: boolean }>('/api/operation/stop'),
  operationPause: () => post<{ ok: boolean }>('/api/operation/pause'),
  operationResume: () => post<{ ok: boolean }>('/api/operation/resume'),
  operationInput: (value: string) =>
    post<{ ok: boolean }>('/api/operation/input', { value }),
  // Never raises server-side; always 200 with a report of what was actioned.
  estop: () =>
    post<{ ok: boolean; report: Record<string, unknown> }>('/api/estop'),

  motorsHoldingDismiss: () => post<{ ok: boolean }>('/api/motors-holding/dismiss'),

  torqueEnable: () =>
    post<{ seed: Record<string, number> }>('/api/torque/enable'),
  torqueDisable: () => post('/api/torque/disable'),
  jointsTarget: (angles: Record<string, number>) =>
    post('/api/joints/target', { angles }),
  jointsNeutral: () => post('/api/joints/neutral'),
  jointsZero: () => post('/api/joints/zero'),
  // joints omitted = every loop-controlled joint; a joint list writes
  // exactly those and leaves the rest as they are.
  setGains: (gains: {
    kp: number
    ki: number
    correction_max_deg: number
    joints?: string[]
  }) => post('/api/control/gains', gains),
  // Restore the config gains; joints omitted = every loop-controlled joint.
  resetGains: (joints?: string[]) =>
    post('/api/control/gains/reset', { joints: joints ?? null }),
  setMaxCurrent: (ma: number) => post('/api/control/max_current', { ma }),
  // Omitted fields are left alone. thermal_unlimited clears the thermal
  // budget, which cannot be expressed as a number.
  setFaultBudgets: (body: {
    report_after_reboots?: number
    giveup_after_reboots?: number
    thermal_giveup_after_reboots?: number
    thermal_unlimited?: boolean
    thermal_clear_margin_c?: number
    thermal_hold_all?: boolean
  }) => post('/api/control/fault_budgets', body),
  setPoseSource: (mode: PoseSource) =>
    post<{ control: ControlState }>('/api/control/pose_source', { mode }),
  rebase: () => post('/api/control/rebase'),

  motorsDirect: () => request<DirectMotorSnapshot>('/api/motors/direct'),
  motorsDirectMode: (enabled: boolean) =>
    post<{ direct_mode: boolean }>('/api/motors/direct/mode', { enabled }),
  // Bench range finding: loosen one motor so a human can turn it, then
  // record the two ends they found.
  motorsDirectTorque: (id: number, enabled: boolean) =>
    post<{ id: number; torque_enabled: boolean }>('/api/motors/direct/torque', {
      id,
      enabled,
    }),
  motorsDirectRange: (id: number, low: number | null, high: number | null) =>
    post<{ id: number; range_rad: [number, number] | null }>(
      '/api/motors/direct/range',
      { id, low, high },
    ),
  motorsModels: () =>
    request<{ models: MotorModelInfo[] }>('/api/motors/models'),
  motorsDirectDeclare: (
    id: number,
    model: string | null,
    nickname: string | null,
  ) =>
    post<Record<string, unknown>>('/api/motors/direct/declare', {
      id,
      model,
      nickname,
    }),
  motorsDirectPoints: (id: number, points: number[] | null) =>
    post<{ id: number; points: number[] | null }>('/api/motors/direct/points', {
      id,
      points,
    }),
  motorsDirectPlay: (id: number, enabled: boolean) =>
    post<{ id: number; playing: boolean }>('/api/motors/direct/play', {
      id,
      enabled,
    }),
  motorsDirectPacing: (
    interp_steps: number,
    max_settle_ms: number | null,
    period_ms: number | null,
  ) =>
    post<{
      interp_steps: number
      max_settle_ms: number | null
      period_ms: number
    }>('/api/motors/direct/pacing', { interp_steps, max_settle_ms, period_ms }),
  motorsDirectPosition: (id: number, position: number) =>
    post<{ id: number; position: number; previous: number }>(
      '/api/motors/direct/position',
      { id, position },
    ),

  poses: () => request<{ poses: PoseEntry[] }>('/api/poses'),
  poseSave: (name: string, angles: Record<string, number>) =>
    put<{ ok: boolean }>(`/api/poses/${encodeURIComponent(name)}`, { angles }),
  poseDelete: (name: string) =>
    del<{ ok: boolean }>(`/api/poses/${encodeURIComponent(name)}`),
  poseApply: (name: string) =>
    post<{ name: string; angles: Record<string, number> }>(
      `/api/poses/${encodeURIComponent(name)}/apply`,
    ),
  // Saves the current MEASURED pose (needs encoders; 409 with reason if not).
  poseCapture: (name: string) =>
    post<{ name: string; angles: Record<string, number> }>(
      '/api/poses/capture',
      { name },
    ),

  trajectories: () =>
    request<{ trajectories: TrajectoryEntry[] }>('/api/trajectories'),
  trajectoryGet: (name: string) =>
    request<TrajectoryData>(`/api/trajectories/${encodeURIComponent(name)}`),
  trajectoryUpdate: (name: string, waypoints: number[][], saveAs?: string) =>
    put<{ ok: boolean; name: string; frames: number }>(
      `/api/trajectories/${encodeURIComponent(name)}`,
      { waypoints, save_as: saveAs ?? null },
    ),
  // Translate a joint waypoint recording into raw motor positions through the
  // calibrated joint<->motor map; saved as <name>_motor unless saveAs is given.
  trajectoryToMotor: (name: string, saveAs?: string) =>
    post<{ ok: boolean; name: string; frames: number }>(
      `/api/trajectories/${encodeURIComponent(name)}/to_motor`,
      { save_as: saveAs ?? null },
    ),
  trajectoryDelete: (name: string) =>
    del<{ ok: boolean }>(`/api/trajectories/${encodeURIComponent(name)}`),
  demos: () => request<{ demos: DemoEntry[] }>('/api/demos'),

  setTactileMode: (mode: TactileMode) => post('/api/tactile/mode', { mode }),
  zeroTactile: (numSamples = 100) =>
    post('/api/tactile/zero', { num_samples: numSamples }),
  clearTactileZero: () => post('/api/tactile/clear_zero'),

  appState: () => request<{ session: AppSnapshot }>('/api/app/state'),
  appLog: () => request<OperationLogPayload>('/api/app/log'),
  appList: () => request<{ apps: AppEntry[] }>('/api/app/list'),
  appSetCommand: (app: AppId, command: string) =>
    put<{ apps: AppEntry[] }>(`/api/app/${app}/command`, { command }),
  // Sent to the running app (which confirms on app.state), else remembered.
  appSetValues: (app: AppId, values: Record<string, unknown>) =>
    post<{
      sent: boolean
      values?: Record<string, unknown>
      errors: Record<string, string> // refused keys, with why
    }>(
      `/api/app/${app}/settings`,
      { values },
    ),
  appStart: (app: AppId) =>
    post<{ session: AppSnapshot }>('/api/app/start', { app, mode: 'managed' }),
  // Each names the session the caller shows; another current session is a 409.
  appStop: (sessionId: string | null) =>
    post<{ ok: boolean; stopped: boolean }>('/api/app/stop', {
      session_id: sessionId,
    }),
  appEngage: (sessionId: string | null, rampS?: number) =>
    post<{ session: AppSnapshot }>('/api/app/engage', {
      session_id: sessionId,
      ...(rampS === undefined ? {} : { ramp_s: rampS }),
    }),
  appDisengage: (sessionId: string | null) =>
    post<{ session: AppSnapshot }>('/api/app/disengage', {
      session_id: sessionId,
    }),

  modelMetadata: () => request<ModelMetadata>('/api/model/metadata'),
  modelFingertips: () =>
    request<Record<string, FingertipEntry>>('/api/model/fingertips'),
  // Per-finger T_fingertip_sensor as row-major 4x4 (meters), from orca_core's
  // mesh-registered kinematics data.
  modelSensorMounts: () => request<SensorMounts>('/api/model/sensor_mounts'),
  mockJointSweep: (joint: string | null, periodS = 4.0) =>
    post<{ ok: boolean; sweeping: string | null }>('/api/mock/joint_sweep', {
      joint,
      period_s: periodS,
    }),
}

export interface FingertipEntry {
  link: string
  parent_link: string
  anchor: [number, number, number]
  distal_axis: string
}

export type SensorMounts = Record<string, { matrix: number[][] }>

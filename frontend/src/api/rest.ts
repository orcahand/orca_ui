// Thin fetch wrappers over the REST API. Errors carry the backend's detail.

import type {
  DemoEntry,
  DirectMotorSnapshot,
  HandInfo,
  JointCalibrateResult,
  ModelMetadata,
  OperationLogPayload,
  OperationSnapshot,
  PortInfo,
  PoseEntry,
  Stats,
  StatusSnapshot,
  TactileMode,
  TaxelGeometry,
  TeleopCamera,
  TeleopInstallState,
  TeleopSnapshot,
  TeleopSourceId,
  TeleopSourcesInfo,
  TrajectoryEntry,
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
  ports: () => request<PortInfo[]>('/api/ports'),
  taxelGeometry: () => request<TaxelGeometry>('/api/tactile/geometry'),
  reconnect: () => post('/api/reconnect'),

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

  torqueEnable: () =>
    post<{ seed: Record<string, number> }>('/api/torque/enable'),
  torqueDisable: () => post('/api/torque/disable'),
  jointsTarget: (angles: Record<string, number>) =>
    post('/api/joints/target', { angles }),
  jointsNeutral: () => post('/api/joints/neutral'),
  // Manual joint-sensor calibration: the joint sits at angleDeg right now
  // (operator-verified against the 3D model); re-anchor its encoder there.
  jointCalibrate: (joint: string, angleDeg: number) =>
    post<JointCalibrateResult>('/api/joints/calibrate', {
      joint,
      angle_deg: angleDeg,
    }),
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
  rebase: () => post('/api/control/rebase'),
  setRomFrame: (mode: 'anchor' | 'centered') =>
    post<{ rom_frame: string; requires_reconnect: boolean }>(
      '/api/control/rom_frame',
      { mode },
    ),

  motorsDirect: () => request<DirectMotorSnapshot>('/api/motors/direct'),
  motorsDirectMode: (enabled: boolean) =>
    post<{ direct_mode: boolean }>('/api/motors/direct/mode', { enabled }),
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
  trajectoryDelete: (name: string) =>
    del<{ ok: boolean }>(`/api/trajectories/${encodeURIComponent(name)}`),
  demos: () => request<{ demos: DemoEntry[] }>('/api/demos'),

  setTactileMode: (mode: TactileMode) => post('/api/tactile/mode', { mode }),
  zeroTactile: (numSamples = 100) =>
    post('/api/tactile/zero', { num_samples: numSamples }),
  clearTactileZero: () => post('/api/tactile/clear_zero'),

  teleopState: () => request<{ session: TeleopSnapshot }>('/api/teleop/state'),
  teleopSources: () => request<TeleopSourcesInfo>('/api/teleop/sources'),
  // Slow (probes each device through the streamer child); 409 mid-session.
  teleopScanCameras: () =>
    post<{ cameras: TeleopCamera[]; default_camera_index: number | null }>(
      '/api/teleop/cameras/scan',
    ),
  teleopLog: () => request<OperationLogPayload>('/api/teleop/log'),
  teleopStart: (
    source: TeleopSourceId,
    mode: 'managed' | 'external',
    config: Record<string, unknown> = {},
  ) =>
    post<{ session: TeleopSnapshot; token?: string }>('/api/teleop/start', {
      source,
      mode,
      config,
    }),
  teleopStop: () => post<{ ok: boolean; stopped: boolean }>('/api/teleop/stop'),
  teleopEngage: (rampS?: number) =>
    post<{ session: TeleopSnapshot }>(
      '/api/teleop/engage',
      rampS === undefined ? {} : { ramp_s: rampS },
    ),
  teleopDisengage: () =>
    post<{ session: TeleopSnapshot }>('/api/teleop/disengage'),
  teleopConfig: (config: Record<string, unknown>) =>
    post<{ config: Record<string, unknown> }>('/api/teleop/config', { config }),

  // Install works with teleop disabled — it is what makes teleop possible.
  teleopInstallState: (path?: string) =>
    request<TeleopInstallState>(
      '/api/teleop/install' +
        (path ? `?path=${encodeURIComponent(path)}` : ''),
    ),
  teleopInstallLog: () =>
    request<OperationLogPayload>('/api/teleop/install/log'),
  teleopInstall: (path?: string) =>
    post<TeleopInstallState>('/api/teleop/install', path ? { path } : {}),
  teleopInstallCancel: () =>
    post<{ ok: boolean }>('/api/teleop/install/cancel'),

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

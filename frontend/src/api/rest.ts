// Thin fetch wrappers over the REST API. Errors carry the backend's detail.

import type {
  HandInfo,
  JointCalibrationEntry,
  ModelMetadata,
  Stats,
  StatusSnapshot,
  TactileMode,
  TaxelGeometry,
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

export const api = {
  status: () => request<StatusSnapshot>('/api/status'),
  handInfo: () => request<HandInfo>('/api/hand/info'),
  stats: () => request<Stats>('/api/stats'),
  taxelGeometry: () => request<TaxelGeometry>('/api/tactile/geometry'),
  reconnect: () => post('/api/reconnect'),

  torqueEnable: () =>
    post<{ seed: Record<string, number> }>('/api/torque/enable'),
  torqueDisable: () => post('/api/torque/disable'),
  jointsTarget: (angles: Record<string, number>) =>
    post('/api/joints/target', { angles }),
  jointsNeutral: () => post('/api/joints/neutral'),
  setGains: (gains: {
    kp: number
    ki: number
    correction_max_deg: number
    i_clamp_deg?: number
  }) => post('/api/control/gains', gains),
  setMaxCurrent: (ma: number) => post('/api/control/max_current', { ma }),
  rebase: () => post('/api/control/rebase'),

  setTactileMode: (mode: TactileMode) => post('/api/tactile/mode', { mode }),
  zeroTactile: (numSamples = 100) =>
    post('/api/tactile/zero', { num_samples: numSamples }),
  clearTactileZero: () => post('/api/tactile/clear_zero'),

  modelMetadata: () => request<ModelMetadata>('/api/model/metadata'),
  modelCalibration: () =>
    request<{ schema: number; joints: Record<string, JointCalibrationEntry> }>(
      '/api/model/calibration',
    ),
  modelFingertips: () =>
    request<Record<string, unknown>>('/api/model/fingertips'),
}

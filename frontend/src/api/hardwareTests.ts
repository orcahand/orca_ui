// REST client and wire types for the hardware-tests tab (/api/hardware-tests).
// Field names follow orca_ui/hardware_tests/model.py.

import { ApiError } from './rest'

export type HwStepKind = 'manual' | 'auto' | 'compare' | 'observe'
export type HwStepStatus =
  'pending' | 'running' | 'pass' | 'fail' | 'observed' | 'skipped' | 'error'
export type HwDecision = 'pass' | 'fail' | 'observed' | 'skipped'
export type HwSideName = 'main' | 'branch'
export type HwPanel =
  | 'motor_positions'
  | 'motor_currents'
  | 'motor_temperatures'
  | 'joint_encoders'
  | 'tactile'
  | 'operation_log'

export const DECIDED_STATUSES: ReadonlySet<HwStepStatus> = new Set([
  'pass',
  'fail',
  'observed',
  'skipped',
])

export interface HwAppliesTo {
  motor_families: string[]
  hardware_versions: number[]
  sides: string[]
  requires: string[]
}

export interface HwMetric {
  name: string
  value: number | string | null
  unit: string
  // The same quantity measured with main's orca_core (compare steps).
  main: number | string | null
  ok: boolean | null
}

export interface HwSeries {
  name: string
  x: number[]
  y: number[]
  side: HwSideName | 'console'
  x_label: string
  y_label: string
}

export interface HwCheckResult {
  status: 'pass' | 'fail' | 'observed' | 'skipped' | 'error'
  summary: string
  metrics: HwMetric[]
  series: HwSeries[]
  details: Record<string, unknown>
}

export interface HwStepResult {
  step_id: string
  status: HwStepStatus
  note: string
  decided_by: '' | 'person' | 'check'
  check: HwCheckResult | null
  screenshots: string[]
  started_at: string | null
  finished_at: string | null
}

export interface HwStep {
  id: string
  title: string
  kind: HwStepKind
  instructions: string
  pass_rule: string
  applies_to: HwAppliesTo
  panels: HwPanel[]
  action: string | null
  check: string | null
  params: Record<string, unknown>
  applicable: boolean
  not_applicable_reason: string | null
  // The backend's own section split; the tab falls back to the kind rule without it.
  hands_on?: boolean
  automatic?: boolean
  // A decided manual step whose check is verifying the decision.
  verifying?: boolean
  // This step's results folder, with ~ for home.
  folder?: string
  result: HwStepResult
}

export interface HwFeature {
  id: string
  title: string
  summary: string
  group: 'new' | 'existing' | 'observation'
  // Results folder for this feature in this session, with ~ for home.
  folder: string
  steps: HwStep[]
}

export interface HwHandFacts {
  label: string
  model_name: string | null
  motor_family: string | null
  hardware_version: number | null
  hardware_version_source: string | null
  side: string | null
  capabilities: string[]
  mock: boolean
}

export interface HwSideInfo {
  available: boolean
  reason: string | null
  version: string | null
}

export interface HwAutoState {
  state: 'idle' | 'running' | 'stopping'
  current_step: string | null
  progress: number
  detail: string
  log: string[]
}

export interface HwSession {
  id: string
  plan_id: string
  plan_title: string
  started_at: string
  finished_at: string | null
  results_dir: string
  index_file: string
  events_file?: string
  hand: HwHandFacts
  sides: Record<HwSideName, HwSideInfo>
  auto: HwAutoState
  open_step: string | null
  features: HwFeature[]
}

export interface HwPlanSummary {
  id: string
  title: string
  summary: string
}

export interface HwState {
  enabled: boolean
  plans: HwPlanSummary[]
  session: HwSession | null
  // Label the backend proposes for this hand (board serial or unlabeled-<side>-<date>).
  default_label?: string | null
  bench_dir?: string
}

// Keeps the backend's structured detail (e.g. the undecided steps behind a 409).
export class HwApiError extends ApiError {
  detail: unknown
  constructor(status: number, message: string, detail: unknown) {
    super(status, message)
    this.detail = detail
  }
}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    if (typeof record.message === 'string') return record.message
    if (typeof record.reason === 'string') return record.reason
  }
  return JSON.stringify(detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/hardware-tests${path}`, init)
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? body
    } catch {
      /* keep statusText */
    }
    throw new HwApiError(response.status, describe(detail), detail)
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

const step = (id: string) => `/steps/${encodeURIComponent(id)}`

export const hwApi = {
  state: () => request<HwState>('/state'),
  // Starts a session, or resumes an unfinished one with the same plan and label.
  startSession: (planId: string, handLabel: string) =>
    post<HwSession>('/session', { plan_id: planId, hand_label: handLabel }),
  endSession: () => post<Record<string, never>>('/session/end'),
  openStep: (id: string) => post<HwSession>(`${step(id)}/open`),
  closeStep: (id: string) => post<HwSession>(`${step(id)}/close`),
  decide: (id: string, status: HwDecision, note: string) =>
    post<HwSession>(`${step(id)}/result`, { status, note }),
  screenshot: (id: string, png: Blob) =>
    request<{ file: string }>(`${step(id)}/screenshot`, {
      method: 'POST',
      headers: { 'Content-Type': 'image/png' },
      body: png,
    }),
  // 409 while applicable hands-on steps are undecided, unless force.
  runAuto: (opts: { stepIds?: string[]; force?: boolean } = {}) =>
    post<HwSession>('/auto/run', {
      ...(opts.stepIds ? { step_ids: opts.stepIds } : {}),
      force: opts.force ?? false,
    }),
  stopAuto: () => post<HwSession>('/auto/stop'),
}

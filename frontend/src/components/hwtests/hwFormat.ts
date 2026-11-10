// Formatting helpers for the Tests tab.

import type { HwAppliesTo, HwStepKind, HwStepStatus } from '../../api/hardwareTests'

export const STATUS_LABEL: Record<HwStepStatus, string> = {
  pending: 'pending',
  running: 'running',
  pass: 'pass',
  fail: 'fail',
  observed: 'observed',
  skipped: 'skipped',
  error: 'error',
}

export const KIND_LABEL: Record<HwStepKind, string> = {
  manual: 'manual',
  auto: 'auto',
  compare: 'main vs branch',
  observe: 'observe',
}

// 210 -> v2.1.0; older single-digit reports (2, 21) read as v2.0 / v2.1.
export function formatHardwareVersion(version: number | null | undefined): string {
  if (version === null || version === undefined) return 'unknown'
  const normalized = version < 10 ? version * 100 : version < 100 ? version * 10 : version
  const major = Math.floor(normalized / 100)
  const minor = Math.floor((normalized % 100) / 10)
  const patch = normalized % 10
  return `v${major}.${minor}.${patch}`
}

export function appliesToText(appliesTo: HwAppliesTo | undefined): string {
  if (!appliesTo) return 'any hand'
  const parts: string[] = []
  if (appliesTo.motor_families?.length) parts.push(`motors ${appliesTo.motor_families.join(' / ')}`)
  if (appliesTo.hardware_versions?.length)
    parts.push(appliesTo.hardware_versions.map(formatHardwareVersion).join(' / '))
  if (appliesTo.sides?.length) parts.push(`${appliesTo.sides.join(' / ')} hands`)
  if (appliesTo.requires?.length) parts.push(`needs ${appliesTo.requires.join(' + ')}`)
  return parts.length ? parts.join(' · ') : 'any hand'
}

export function formatValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (!Number.isFinite(value)) return String(value)
  if (Number.isInteger(value)) return String(value)
  const magnitude = Math.abs(value)
  return value.toFixed(magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 3)
}

export function difference(
  branch: number | string | null | undefined,
  main: number | string | null | undefined,
): string {
  if (typeof branch !== 'number' || typeof main !== 'number') {
    if (branch === null || branch === undefined || main === null || main === undefined) return '—'
    return branch === main ? 'same' : 'differs'
  }
  const delta = branch - main
  const sign = delta > 0 ? '+' : ''
  const pct = main !== 0 ? ` (${sign}${((delta / Math.abs(main)) * 100).toFixed(0)}%)` : ''
  return `${sign}${formatValue(delta)}${pct}`
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

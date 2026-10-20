// The servo's own position PID, feedforward, and trajectory limits, per motor.
//
// Not the Control Loop panel's gains: those are the host's outer-loop PI trim
// on encoder hands, while these live inside the motor and close the loop the
// host trims. Both exist and they interact, so they are kept visibly apart.
//
// Everything here is read off the motors rather than remembered. These are all
// RAM registers: a power cycle clears them, and a value we merely typed would
// be a lie. Reading costs two bus transactions, so it happens on demand.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type {
  ServoGains,
  ServoGainsMap,
  ServoLimits,
  ServoProfile,
  ServoProfileMap,
} from '../../api/types'
import { corePredates } from '../../api/coreVersion'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'

type GainField = keyof ServoGains
type ProfileField = keyof ServoProfile

// Fallback only, for a backend too old to report the width. Families differ:
// X-series gain registers are two bytes, HLS gains one.
const GAIN_MAX_FALLBACK = 16383
// The release that first reported Feetech gains. Below it the console asks
// and gets nothing back, which is indistinguishable from a family that has
// no such registers — so say which it is rather than showing an empty table.
const CORE_WITH_FEETECH_GAINS = '0.5.1'

const GAIN_FIELDS: { key: GainField; label: string; title: string }[] = [
  { key: 'kp', label: 'Kp', title: 'Position P gain — stiffness against position error.' },
  { key: 'ki', label: 'Ki', title: 'Position I gain — removes steady-state droop, at the cost of windup.' },
  { key: 'kd', label: 'Kd', title: 'Position D gain — damping; too much amplifies encoder noise.' },
  {
    key: 'ff_1st',
    label: 'FF1',
    title:
      'Velocity feedforward: scales the desired trajectory’s velocity, ' +
      'cancelling the lag of tracking a moving target without spending ' +
      'stability margin on Kp. Does nothing while VEL is 0 — a step has no ' +
      'trajectory to differentiate.',
  },
  {
    key: 'ff_2nd',
    label: 'FF2',
    title:
      'Acceleration feedforward: acts where acceleration is largest — ' +
      'profile corners and direction reversals. Also inert while ACC is 0.',
  },
]

const PROFILE_FIELDS: {
  key: ProfileField
  label: string
  max: number
  title: string
}[] = [
  {
    key: 'velocity_rad_s',
    label: 'VEL rad/s',
    max: 100,
    title:
      'Speed cap for the servo’s own trajectory. 0 = uncapped. This is a ' +
      'slew-rate limit, not a filter: motion under the cap passes through ' +
      'untouched. It limits streamed targets too, which is a safety property ' +
      'for teleop and an unwanted lag inside a tuned loop.',
  },
  {
    key: 'acceleration_rad_s2',
    label: 'ACC rad/s²',
    max: 10000,
    title:
      'Ramp rate toward the speed cap. 0 = instantaneous. Set this low ' +
      'enough that the cap is not reached within one command interval and ' +
      'every step is attenuated, not just the fast ones.',
  },
]

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

// Spans across the chain, because the motors on one bus do not share a
// ceiling: a wrist and a finger joint answer with different limits.
function spread(values: number[], unit: string, digits = 1): string {
  if (values.length === 0) return '--'
  const low = Math.min(...values)
  const high = Math.max(...values)
  return low === high
    ? `${high.toFixed(digits)} ${unit}`
    : `${low.toFixed(digits)}–${high.toFixed(digits)} ${unit}`
}

/** What the boxes below will accept, and what the ends of the range mean.
 *
 * The reachable ceiling rather than the register width. The registers hold
 * values far beyond anything these motors do and accept them silently, so a
 * legend quoting the register would invite an operator to ask for a speed
 * that does nothing at all.
 */
function LimitsLegend({
  limits,
  maxGain,
}: {
  limits: ServoLimits
  maxGain: number
}) {
  const perMotor = Object.values(limits.per_motor ?? {})
  const tunables = limits.tunables ?? {}
  const accelMax = tunables.acceleration_rad_s2?.max ?? null
  return (
    <div
      style={{
        fontSize: 10,
        color: 'var(--dimmer)',
        marginBottom: 6,
        borderLeft: '2px solid var(--dimmer)',
        paddingLeft: 6,
      }}
    >
      <div>
        <b>KP/KI/KD/FF</b> 0–{maxGain} · 0 ={' '}
        {tunables.gain?.zero_means ?? 'no contribution from this term'}
      </div>
      {perMotor.length > 0 && (
        <div>
          <b>VEL</b> 0–
          {spread(perMotor.map((m) => m.velocity_rad_s), 'rad/s', 2)} · 0 = no
          speed cap · above this the motor simply turns as fast as it can
        </div>
      )}
      {accelMax !== null && (
        <div>
          <b>ACC</b> 0–{accelMax.toFixed(0)} rad/s² · 0 = maximum acceleration
        </div>
      )}
      {tunables.velocity_rad_s?.ceiling_source && (
        <div style={{ opacity: 0.8 }}>
          ceiling from {tunables.velocity_rad_s.ceiling_source}
        </div>
      )}
    </div>
  )
}

export function ServoTuningPanel() {
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const core = useAppStore((s) => s.handInfo?.core)
  const setError = useAppStore((s) => s.setError)

  const [gains, setGains] = useState<ServoGainsMap | null>(null)
  const [gainMax, setGainMax] = useState<number | null>(null)
  const [profile, setProfile] = useState<ServoProfileMap | null>(null)
  const [limits, setLimits] = useState<ServoLimits | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [columnDrafts, setColumnDrafts] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)

  const jointOfMotor = new Map<string, string>()
  for (const joint of joints ?? []) {
    if (joint.motor_id !== null && joint.motor_id !== undefined) {
      jointOfMotor.set(String(joint.motor_id), joint.id)
    }
  }

  const refresh = useCallback(() => {
    if (!motors) return
    setLoading(true)
    Promise.all([api.servoGains(), api.servoProfile()])
      .then(([g, p]) => {
        setGains(g.gains)
        setGainMax(g.gain_max ?? null)
        setProfile(p.profile)
        setLimits(p.limits ?? null)
        setDrafts({})
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setLoading(false))
  }, [motors, setError])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (!motors) return null

  const maxGain = gainMax ?? GAIN_MAX_FALLBACK
  // A field every motor reports as null is a register this family does not
  // have. Showing an empty column for it invites tuning against a term that
  // does not exist, so the column is dropped rather than greyed out.
  const entries = Object.values(gains ?? {})
  const profileEntries = Object.values(profile ?? {})
  const profileFields = PROFILE_FIELDS.filter(
    (f) =>
      profileEntries.length === 0 ||
      profileEntries.some((p) => p !== null && p[f.key] !== null &&
                                 p[f.key] !== undefined),
  )
  const gainFields = GAIN_FIELDS.filter(
    (f) =>
      entries.length === 0 ||
      entries.some((g) => g !== null && g[f.key] !== null &&
                          g[f.key] !== undefined),
  )

  // Set one column on every motor at once. A chain is tuned as a set, and
  // typing the same number seventeen times invites one typo that is then very
  // hard to spot in a table of near-identical numbers.
  const setAllColumn = (
    key: string,
    label: string,
    max: number,
    integer: boolean,
  ) => {
    const raw = (columnDrafts[key] ?? '').trim()
    if (raw === '') return
    const value = integer ? Number.parseInt(raw, 10) : Number.parseFloat(raw)
    if (!Number.isFinite(value) || value < 0 || value > max) {
      setError(`${label} must be 0–${max}`)
      return
    }
    setBusy('all')
    const send = (id: string) =>
      integer
        ? api.setServoGains(Number(id), { [key]: value })
        : api.setServoProfile(Number(id), { [key]: value })
    Promise.all(ids.map(send))
      .then(() => {
        setColumnDrafts((d) => ({ ...d, [key]: '' }))
        setError(null)
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => {
        setBusy(null)
        refresh()
      })
  }

  // One header cell: the label, a value for the whole column, and the button
  // that writes it everywhere.
  const columnHeader = (
    key: string,
    label: string,
    title: string,
    max: number,
    integer: boolean,
  ) => (
    <th key={key} title={title}>
      {/* Stacked and left-aligned together: the header's own text alignment
          would otherwise leave the label sitting off the corner of the box. */}
      <div style={{ display: 'flex', flexDirection: 'column',
                    alignItems: 'flex-start', gap: 2 }}>
        <span>{label}</span>
        <div style={{ display: 'flex', gap: 2 }}>
          <input
            type="number"
            min={0}
            max={max}
            step={integer ? 1 : 0.1}
            placeholder="all"
            value={columnDrafts[key] ?? ''}
            disabled={busy !== null || loading}
            title={`set ${label} on all ${ids.length} motors`}
            onChange={(e) =>
              setColumnDrafts((d) => ({ ...d, [key]: e.target.value }))
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter') setAllColumn(key, label, max, integer)
            }}
            style={{ width: 46, fontSize: 9 }}
          />
          <button
            className="btn btn-secondary"
            style={{ padding: '0 4px', fontSize: 9 }}
            disabled={
              busy !== null || loading || (columnDrafts[key] ?? '').trim() === ''
            }
            title={`write this to all ${ids.length} motors`}
            onClick={() => setAllColumn(key, label, max, integer)}
          >
            set
          </button>
        </div>
      </div>
    </th>
  )

  const nothingSettable = gainFields.length === 0 && profileFields.length === 0
  // A development checkout carries whatever version it was cut from, so its
  // number says nothing about what it contains: never blame it.
  const coreTooOld =
    nothingSettable && corePredates(core, CORE_WITH_FEETECH_GAINS)

  const apply = (id: string) => {
    const draft = drafts[id] ?? {}
    const gainPayload: Partial<ServoGains> = {}
    const profilePayload: Partial<ServoProfile> = {}

    for (const { key } of gainFields) {
      const raw = draft[key]
      if (raw === undefined || raw === '') continue
      const value = Number.parseInt(raw, 10)
      if (!Number.isFinite(value) || value < 0 || value > maxGain) {
        setError(`${key} must be 0–${maxGain}`)
        return
      }
      gainPayload[key] = value
    }
    for (const { key, max } of profileFields) {
      const raw = draft[key]
      if (raw === undefined || raw === '') continue
      const value = Number.parseFloat(raw)
      if (!Number.isFinite(value) || value < 0 || value > max) {
        setError(`${key} must be 0–${max}`)
        return
      }
      profilePayload[key] = value
    }
    if (!Object.keys(gainPayload).length && !Object.keys(profilePayload).length) {
      return
    }

    setBusy(id)
    const calls: Promise<unknown>[] = []
    if (Object.keys(gainPayload).length) {
      calls.push(api.setServoGains(Number(id), gainPayload)
        .then((r) => setGains(r.gains)))
    }
    if (Object.keys(profilePayload).length) {
      calls.push(api.setServoProfile(Number(id), profilePayload)
        .then((r) => setProfile(r.profile)))
    }
    Promise.all(calls)
      .then(() => {
        setDrafts((d) => ({ ...d, [id]: {} }))
        setError(null)
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(null))
  }

  const ids = Object.keys(gains ?? {}).sort((a, b) => Number(a) - Number(b))
  const toolbar = (
    <button className="btn btn-secondary" onClick={refresh} disabled={loading}
            title="Re-read gains and profile from the motors">
      {loading ? '…' : 'read'}
    </button>
  )

  const cell = (
    id: string,
    key: string,
    shown: number | null | undefined,
    max: number,
    step: number,
  ) => (
    <td key={key}>
      <input
        type="number"
        min={0}
        max={max}
        step={step}
        style={{ width: 62 }}
        placeholder={fmt(shown)}
        value={drafts[id]?.[key] ?? ''}
        // null is a register this family does not have, not one that is
        // merely unset: a Feetech position loop is PID with no feedforward,
        // and offering the field would only produce a refusal.
        disabled={shown === undefined || shown === null || busy === id}
        title={
          shown === null
            ? 'this motor family does not have this register'
            : undefined
        }
        onChange={(e) =>
          setDrafts((d) => ({
            ...d,
            [id]: { ...(d[id] ?? {}), [key]: e.target.value },
          }))
        }
        onKeyDown={(e) => {
          if (e.key === 'Enter') apply(id)
        }}
      />
    </td>
  )

  return (
    <Panel title="Servo Tuning" toolbar={toolbar}>
      <div style={{ fontSize: 10, color: 'var(--dimmer)', marginBottom: 6 }}>
        the motor’s own PID and trajectory limits — separate from the host
        Control Loop trim. RAM registers: a power cycle clears them, and what
        you set here is re-applied on torque enable. VEL/ACC of 0 disables that
        limit; non-zero also rate-limits streamed targets, so it shapes teleop
        and replay, not just point-to-point moves.
      </div>
      {limits && <LimitsLegend limits={limits} maxGain={maxGain} />}
      {ids.length === 0 || nothingSettable ? (
        <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
          {loading ? (
            'reading…'
          ) : coreTooOld ? (
            <>
              <span style={{ color: 'var(--warn)' }}>
                orca_core {core?.version} does not report this motor family’s
                gains.
              </span>{' '}
              {CORE_WITH_FEETECH_GAINS} does. Update with{' '}
              <code>git pull &amp;&amp; uv sync</code> and reconnect.
            </>
          ) : (
            'nothing reported — this motor family may not expose these registers'
          )}
        </div>
      ) : (
        <table className="motor-table">
          <thead>
            <tr>
              <th>MOTOR</th>
              <th>JOINT</th>
              {gainFields.map((f) =>
                columnHeader(f.key, f.label, f.title, maxGain, true))}
              {profileFields.map((f) =>
                columnHeader(f.key, f.label, f.title, f.max, false))}
              <th aria-label="apply" />
            </tr>
          </thead>
          <tbody>
            {ids.map((id) => {
              const g = gains?.[id] ?? null
              const p = profile?.[id] ?? null
              const draft = drafts[id] ?? {}
              const dirty = Object.values(draft).some((v) => v !== undefined && v !== '')
              return (
                <tr key={id}>
                  <td>{id}</td>
                  <td className="motor-joint">{jointOfMotor.get(id) ?? '--'}</td>
                  {gainFields.map((f) =>
                    cell(id, f.key, g === null ? undefined : g[f.key], maxGain, 1))}
                  {profileFields.map((f) =>
                    cell(id, f.key, p === null ? undefined : p[f.key], f.max, 0.1))}
                  <td>
                    <button
                      className="btn btn-secondary"
                      disabled={!dirty || busy === id}
                      title={dirty ? 'write these values to the motor'
                                   : 'type a value to change'}
                      onClick={() => apply(id)}
                    >
                      {busy === id ? '…' : 'set'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

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
  ServoProfile,
  ServoProfileMap,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'

type GainField = keyof ServoGains
type ProfileField = keyof ServoProfile

// The X-series PID registers are unsigned 16-bit, capped at 16383.
const GAIN_MAX = 16383

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

export function ServoTuningPanel() {
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const setError = useAppStore((s) => s.setError)

  const [gains, setGains] = useState<ServoGainsMap | null>(null)
  const [profile, setProfile] = useState<ServoProfileMap | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({})
  const [busy, setBusy] = useState<string | null>(null)
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
        setProfile(p.profile)
        setDrafts({})
      })
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setLoading(false))
  }, [motors, setError])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (!motors) return null

  const apply = (id: string) => {
    const draft = drafts[id] ?? {}
    const gainPayload: Partial<ServoGains> = {}
    const profilePayload: Partial<ServoProfile> = {}

    for (const { key } of GAIN_FIELDS) {
      const raw = draft[key]
      if (raw === undefined || raw === '') continue
      const value = Number.parseInt(raw, 10)
      if (!Number.isFinite(value) || value < 0 || value > GAIN_MAX) {
        setError(`${key} must be 0–${GAIN_MAX}`)
        return
      }
      gainPayload[key] = value
    }
    for (const { key, max } of PROFILE_FIELDS) {
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
        disabled={shown === undefined || busy === id}
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
      {ids.length === 0 ? (
        <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
          {loading
            ? 'reading…'
            : 'nothing reported — this motor family may not expose these registers'}
        </div>
      ) : (
        <table className="motor-table">
          <thead>
            <tr>
              <th>MOTOR</th>
              <th>JOINT</th>
              {GAIN_FIELDS.map((f) => (
                <th key={f.key} title={f.title}>{f.label}</th>
              ))}
              {PROFILE_FIELDS.map((f) => (
                <th key={f.key} title={f.title}>{f.label}</th>
              ))}
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
                  {GAIN_FIELDS.map((f) =>
                    cell(id, f.key, g === null ? undefined : g[f.key], GAIN_MAX, 1))}
                  {PROFILE_FIELDS.map((f) =>
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

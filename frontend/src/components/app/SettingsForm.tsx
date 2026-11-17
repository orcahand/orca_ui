// The settings an app describes, drawn as a plain form. While the app runs a
// change goes to it and the field shows what it applied (or why it refused);
// otherwise the change is remembered for the next start. While engaged, only
// settings the app marks `live` can change.

import { useState, type ReactNode } from 'react'
import { api } from '../../api/rest'
import type { AppEntry, AppId, AppSetting, AppSnapshot } from '../../api/types'
import { isAppActive, useAppSessionStore } from '../../state/appSessionStore'
import { Panel } from '../common/Panel'
import { fail } from './actions'

export function SettingsForm({
  app,
  entry,
  session,
}: {
  app: AppId
  entry: AppEntry | null
  session: AppSnapshot | null
}) {
  const live = isAppActive(session)
  const schema = live ? session!.settings.schema : (entry?.schema ?? [])
  const values = live ? session!.settings.values : (entry?.values ?? {})
  const engaged = session?.state === 'engaged'
  // Refusals by the console itself, kept only for the session they came from.
  const scope = live ? session!.session_id : null
  const [refused, setRefused] = useState<{
    scope: string | null
    errors: Record<string, string>
  }>({ scope: null, errors: {} })
  const local = refused.scope === scope ? refused.errors : {}
  const errors = { ...(live ? session!.settings.errors : {}), ...local }

  const refuse = (key: string, error: string | undefined) =>
    setRefused((r) => {
      const { [key]: _, ...rest } = r.scope === scope ? r.errors : {}
      return { scope, errors: error ? { ...rest, [key]: error } : rest }
    })

  const change = (setting: AppSetting, value: unknown) => {
    const problem = checkValue(setting, value)
    refuse(setting.key, problem)
    if (problem) return
    void api
      .appSetValues(app, { [setting.key]: value })
      .then((reply) => {
        refuse(setting.key, reply.errors?.[setting.key])
        if (!live) void useAppSessionStore.getState().refreshApps()
      })
      .catch(fail)
  }

  return (
    <Panel title="Settings">
      {schema.length === 0 ? (
        <p className="setup-card-hint">
          {live
            ? 'The app has not described any settings.'
            : 'Settings appear after the first start.'}
        </p>
      ) : (
        <div className="app-settings">
          {schema.map((setting) => {
            const locked = engaged && !setting.live
            return (
              <Field
                key={setting.key}
                setting={setting}
                error={errors[setting.key]}
                note={
                  locked
                    ? 'disengage to change'
                    : setting.restart && live
                      ? 'applies on the next start'
                      : null
                }
              >
                <Control
                  setting={setting}
                  value={values[setting.key] ?? setting.default}
                  disabled={locked}
                  onChange={(value) => change(setting, value)}
                />
              </Field>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

// The same check the backend makes, so a bad number is flagged before it's sent.
function checkValue(setting: AppSetting, value: unknown): string | undefined {
  if (setting.type !== 'number' && setting.type !== 'integer') return undefined
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'must be a number'
  if (setting.type === 'integer' && !Number.isInteger(value))
    return 'must be a whole number'
  if (setting.minimum !== undefined && value < setting.minimum)
    return `must be at least ${setting.minimum}`
  if (setting.maximum !== undefined && value > setting.maximum)
    return `must be at most ${setting.maximum}`
  return undefined
}

function Field({
  setting,
  error,
  note,
  children,
}: {
  setting: AppSetting
  error?: string
  note: string | null
  children: ReactNode
}) {
  return (
    <div className="app-setting">
      <label className="app-setting-label" htmlFor={`setting-${setting.key}`}>
        {setting.title ?? setting.key}
      </label>
      {children}
      {(error || note || setting.help) && (
        <span className={`app-setting-help${error ? ' error' : ''}`}>
          {error ?? note ?? setting.help}
        </span>
      )}
    </div>
  )
}

function Control({
  setting,
  value,
  disabled,
  onChange,
}: {
  setting: AppSetting
  value: unknown
  disabled: boolean
  onChange: (value: unknown) => void
}) {
  const id = `setting-${setting.key}`
  switch (setting.type) {
    case 'boolean':
      return (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
      )
    case 'enum': {
      const choices = setting.choices ?? []
      const index = choices.findIndex((c) => c.value === value)
      return (
        <select
          id={id}
          value={index}
          disabled={disabled}
          onChange={(e) => onChange(choices[Number(e.target.value)]?.value)}
        >
          {index < 0 && <option value={-1}>—</option>}
          {choices.map((choice, i) => (
            <option key={i} value={i}>
              {choice.title ?? String(choice.value)}
            </option>
          ))}
        </select>
      )
    }
    default:
      return <TypedInput setting={setting} value={value} disabled={disabled} onChange={onChange} />
  }
}

// Sent on Enter or when the field loses focus. The field then shows what the
// app reports, so a refused value doesn't linger next to its error.
function TypedInput({
  setting,
  value,
  disabled,
  onChange,
}: {
  setting: AppSetting
  value: unknown
  disabled: boolean
  onChange: (value: unknown) => void
}) {
  const [commits, setCommits] = useState(0)
  const id = `setting-${setting.key}`
  const numeric = setting.type === 'number' || setting.type === 'integer'
  const commit = (raw: string) => {
    const next = numeric ? Number(raw) : raw
    if (raw === '' || next === value) return
    setCommits((n) => n + 1)
    onChange(next)
  }
  return (
    <input
      id={id}
      key={`${String(value)}/${commits}`}
      type={numeric ? 'number' : 'text'}
      defaultValue={value == null ? '' : String(value)}
      min={setting.minimum}
      max={setting.maximum}
      step={setting.type === 'integer' ? 1 : 'any'}
      disabled={disabled}
      onBlur={(e) => commit(e.target.value)}
      onKeyDown={(e) => e.key === 'Enter' && commit(e.currentTarget.value)}
    />
  )
}

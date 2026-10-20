// Configuration registers for one motor at a time, on the bare bench.
//
// Collapsed until opened: these are EEPROM settings that survive a power
// cycle, and two of them move the motor on the bus. Nothing here should be
// one stray click away.
//
// Every row comes from what the connected family declares. A family without
// a setting sends no row for it, so nothing is greyed out against a list the
// browser holds.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type {
  DirectMotorInfo,
  MotorConfigRegister,
  MotorConfigSchema,
} from '../../api/types'
import {
  CORE_WITH_CONFIG_REGISTERS,
  corePredates,
  updateHint,
} from '../../api/coreVersion'
import { useAppStore } from '../../state/appStore'
import { RegisterPopover } from './RegisterPopover'

export function MotorRegisterPanel({ onClose }: { onClose: () => void }) {
  const setError = useAppStore((s) => s.setError)
  const core = useAppStore((s) => s.handInfo?.core)
  const [motors, setMotors] = useState<DirectMotorInfo[]>([])
  const [schema, setSchema] = useState<MotorConfigSchema | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [values, setValues] = useState<Record<string, number | null>>({})
  const [taken, setTaken] = useState<number[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [noSchema, setNoSchema] = useState(false)

  const fail = useCallback(
    (e: unknown) => setError(String((e as Error).message ?? e)),
    [setError],
  )

  const coreTooOld = corePredates(core, CORE_WITH_CONFIG_REGISTERS)

  useEffect(() => {
    void api
      .motorConfigSchema()
      .then(setSchema)
      .catch((e) => {
        setNoSchema(true)
        // On an older core the refusal says the family declares no editable
        // registers, which is true of every family it has ever seen. Reporting
        // that as an error would send someone looking at their hardware.
        if (!coreTooOld) fail(e)
      })
    void api
      .motorsDirect()
      .then((r) => setMotors(r.motors ?? []))
      .catch(fail)
  }, [fail, coreTooOld])

  const load = useCallback(
    (id: number) => {
      setSelected(id)
      setDrafts({})
      setOutcome(null)
      void api
        .motorConfigRead(id)
        .then((r) => setValues(r.values))
        .catch(fail)
      void api
        .motorConfigTakenIds()
        .then((r) => setTaken(r.ids))
        .catch(fail)
    },
    [fail],
  )

  const apply = (entry: MotorConfigRegister) => {
    if (selected === null) return
    const raw = (drafts[entry.key] ?? '').trim()
    if (raw === '') return
    const value = parseInt(raw, 10)
    if (!Number.isFinite(value)) return
    if (
      entry.reidentifies &&
      !window.confirm(
        `${entry.label}: ${entry.note}.\n\n` +
          'This is an EEPROM write and survives a power cycle. Continue?',
      )
    )
      return
    setBusy(entry.key)
    void api
      .motorConfigWrite(selected, entry.key, value)
      .then((r) => {
        setOutcome(
          r.applied
            ? `${entry.label} is now ${r.actual}` +
                (r.rescanned ? ' — bench re-scanned' : '')
            : `${entry.label} read back as ${r.actual}, not ${r.requested}`,
        )
        setDrafts((d) => ({ ...d, [entry.key]: '' }))
        setError(null)
        // An id change moves the motor; follow it.
        load(r.id)
      })
      .catch(fail)
      .finally(() => setBusy(null))
  }

  const label = (m: DirectMotorInfo) =>
    [`ID ${m.id}`, m.model?.label, m.nickname].filter(Boolean).join(' — ')

  return (
    <RegisterPopover
      title="Control table"
      warning={
        'EEPROM settings: they need torque off and survive a power cycle. ' +
        'Changing an ID moves the motor on the bus.'
      }
      width={430}
      onClose={onClose}
    >
      <select
        value={selected ?? ''}
        onChange={(e) =>
          e.target.value === '' ? setSelected(null) : load(Number(e.target.value))
        }
        style={{ fontSize: 11, minWidth: 240 }}
      >
        <option value="">select a motor…</option>
        {motors.map((m) => (
          <option key={m.id} value={m.id}>
            {label(m)}
          </option>
        ))}
      </select>

      {noSchema && coreTooOld && (
        <div style={{ marginTop: 8, fontSize: 10, color: 'var(--dimmer)' }}>
          <span style={{ color: 'var(--warn)' }}>
            orca_core {core?.version} does not declare which registers an
            operator may edit.
          </span>{' '}
          {CORE_WITH_CONFIG_REGISTERS} does. Update with{' '}
          <code>{updateHint()}</code> and reconnect.
        </div>
      )}

      {selected !== null && schema && (
        <table className="motor-table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>setting</th>
              <th>now</th>
              <th>set to</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {schema.registers.map((entry) => (
              <Row
                key={entry.key}
                entry={entry}
                current={values[entry.key] ?? null}
                draft={drafts[entry.key] ?? ''}
                taken={entry.key === 'id' ? taken : []}
                idRange={schema.id_range}
                selected={selected}
                busy={busy === entry.key}
                onDraft={(v) => setDrafts((d) => ({ ...d, [entry.key]: v }))}
                onApply={() => apply(entry)}
              />
            ))}
          </tbody>
        </table>
      )}
      {outcome && (
        <div style={{ marginTop: 6, color: 'var(--dim)' }}>{outcome}</div>
      )}
    </RegisterPopover>
  )
}

function Row({
  entry,
  current,
  draft,
  taken,
  idRange,
  selected,
  busy,
  onDraft,
  onApply,
}: {
  entry: MotorConfigRegister
  current: number | null
  draft: string
  taken: number[]
  idRange: [number, number]
  selected: number
  busy: boolean
  onDraft: (v: string) => void
  onApply: () => void
}) {
  const shown =
    current === null
      ? '--'
      : entry.choices
        ? (entry.choices[String(current)] ?? `${current} (unknown)`)
        : `${current}${entry.unit ? ' ' + entry.unit : ''}`

  // Baud is a property of the bus, not of a motor: a port carries one rate,
  // so setting a single motor's would orphan it from the chain. Shown here
  // because a motor stranded at the wrong rate is worth seeing; changed only
  // from the bus control.
  if (entry.key === 'baud_rate') {
    return (
      <tr>
        <td title={`${entry.note} (address ${entry.address})`}>{entry.label}</td>
        <td style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</td>
        <td colSpan={2} style={{ color: 'var(--dimmer)' }}>
          set from Bus baud rate — one motor cannot change alone
        </td>
      </tr>
    )
  }

  return (
    <tr>
      <td title={`${entry.note} (address ${entry.address})`}>{entry.label}</td>
      <td style={{ fontVariantNumeric: 'tabular-nums' }}>{shown}</td>
      <td>
        {entry.choices ? (
          <select
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            style={{ fontSize: 10 }}
          >
            <option value="">--</option>
            {Object.entries(entry.choices).map(([raw, meaning]) => (
              <option key={raw} value={raw}>
                {meaning}
              </option>
            ))}
          </select>
        ) : entry.key === 'id' ? (
          <select
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            style={{ fontSize: 10 }}
            title="ids already answering on this bus are not offered"
          >
            <option value="">--</option>
            {idOptions(idRange, taken, selected).map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="number"
            min={entry.min ?? undefined}
            max={entry.max ?? undefined}
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            style={{ width: 70, fontSize: 10 }}
          />
        )}
      </td>
      <td>
        <button
          className="btn btn-secondary"
          disabled={draft === '' || busy}
          onClick={onApply}
        >
          {busy ? '…' : 'set'}
        </button>
      </td>
    </tr>
  )
}

/** Ids a motor may move to.
 *
 *  Bounded by what a bench re-scan reaches, not by what the register accepts:
 *  an id outside that writes fine and then the motor appears to vanish, when
 *  in fact it is answering and nothing is looking for it there.
 *
 *  Ids already on the bus are excluded too -- two motors on one id means one
 *  silently takes the other's commands. */
function idOptions(
  idRange: [number, number],
  taken: number[],
  selected: number,
): number[] {
  const [low, high] = idRange
  const out: number[] = []
  for (let id = low; id <= high; id += 1) {
    if (id === selected || !taken.includes(id)) out.push(id)
  }
  return out
}

// Which motors are actually on the bus, and which of them the bench runs as
// what. A scan pings every ID at the family's baud rates (the session is
// closed for its duration). What answered is listed with a "use" box and a
// number per motor — the number is what the bench calls it, the id is the
// servo's — and Apply rewrites the bench config to that set and reconnects.
// A deep scan pings every ID at every baud rate, for a motor left at the
// factory 57,600 or a stray ID. Any found motor can be re-programmed to a new
// ID on the bench's 1 M baud, and the bench motors can all be moved to
// 30 + their number, which keeps the low IDs free for new motors.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/rest'
import type { BusScanExtra, BusScanResult } from '../api/types'
import { useAppStore } from '../state/appStore'
import {
  isOperationActive,
  operationLabel,
  useOperationStore,
} from '../state/operationStore'
import { useBenchStore } from './benchStore'

const BENCH_BAUD = 1_000_000
const ID_BASE = 30

interface Row {
  key: string
  id: number
  model: string
  baud: number
  use: boolean
  number: string // text while editing
  newId: string // re-program target, text while editing
}

function baud(rate: number): string {
  return rate >= 1_000_000 ? `${rate / 1_000_000}M` : `${Math.round(rate / 1000)}k`
}

// Found motors already on the bench keep their number; newcomers take the
// lowest free ones, in id order.
function buildRows(scan: BusScanResult, numbers: Map<number, number>): Row[] {
  const taken = new Set<number>()
  for (const m of scan.motors) {
    const n = numbers.get(m.id)
    if (n !== undefined) taken.add(n)
  }
  let free = 1
  return [...scan.motors]
    .sort((a, b) => a.id - b.id)
    .map((m) => {
      let n = numbers.get(m.id)
      if (n === undefined) {
        while (taken.has(free)) free += 1
        n = free
        taken.add(n)
      }
      return {
        key: `${m.id}-${m.baud_rate}`,
        id: m.id,
        model: m.model_name,
        baud: m.baud_rate,
        use: m.baud_rate === BENCH_BAUD,
        number: String(n),
        newId: '',
      }
    })
}

export function BusPanel({ connected }: { connected: boolean }) {
  const operation = useOperationStore((s) => s.operation)
  const handInfo = useAppStore((s) => s.handInfo)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const scan = useBenchStore((s) => s.scan)
  const setScan = useBenchStore((s) => s.setScan)
  const motors = useBenchStore((s) => s.motors)
  const remapIds = useBenchStore((s) => s.remapIds)
  const [busy, setBusy] = useState(false)
  const remapped = useRef<string | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  // Folded by default; opens itself while scanning and when a scan has
  // something to decide, folds again once the bench matches the bus.
  const [open, setOpen] = useState(false)

  const active = isOperationActive(operation)
  const scanning = active && operation?.kind === 'bus_scan'
  const programming = active && operation?.kind === 'motor_reprogram'
  const extra = scanning ? (operation?.extra as BusScanExtra | null) : null
  const numbers = useMemo(() => new Map(motors.map((m) => [m.id, m.number])), [motors])

  // Keep the finished scan around after the operation slot moves on, and
  // rebuild the pick list from it.
  useEffect(() => {
    if (operation?.kind === 'bus_scan' && operation.state === 'done' && operation.result) {
      setScan(operation.result as unknown as BusScanResult)
    }
  }, [operation, setScan])
  useEffect(() => {
    setRows(scan ? buildRows(scan, numbers) : [])
  }, [scan, numbers])
  // Re-programmed IDs: the page's own per-motor setup follows, once per run,
  // and the old scan no longer describes the bus.
  useEffect(() => {
    if (operation?.kind !== 'motor_reprogram' || operation.state !== 'done') return
    if (remapped.current === operation.run_id) return
    remapped.current = operation.run_id
    const moved = (operation.result?.moved ?? {}) as Record<string, number>
    if (Object.keys(moved).length) remapIds(moved)
    setScan(null)
  }, [operation, remapIds, setScan])

  const bench = handInfo?.bench ?? false
  const owned = control !== null && control !== undefined && control.control_source !== 'manual'

  let blocked: string | null = null
  if (!wsConnected) blocked = 'backend offline'
  else if (active) blocked = `${operationLabel(operation!.kind)} is running`
  else if (owned) blocked = `control is owned by ${control!.control_owner}`

  const call = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const picked = rows.filter((r) => r.use)
  const parsed = picked.map((r) => ({ id: r.id, number: parseInt(r.number, 10) }))
  const badNumber = parsed.some((p) => !Number.isFinite(p.number) || p.number < 1)
  const duplicate = new Set(parsed.map((p) => p.number)).size !== parsed.length
  const sameAsConfig =
    parsed.length === motors.length &&
    parsed.every((p) => numbers.get(p.id) === p.number)
  let applyBlocked: string | null = null
  if (!bench) applyBlocked = 'the config in force is a hand model — its motor list is not editable here'
  else if (scan?.mixed_baud) applyBlocked = 'motors answer at different baud rates; re-program the odd one first'
  else if (picked.length === 0) applyBlocked = 'tick at least one motor'
  else if (badNumber) applyBlocked = 'every motor needs a number of 1 or more'
  else if (duplicate) applyBlocked = 'two motors have the same number'
  else if (sameAsConfig) applyBlocked = 'this is already the bench'

  const found = scan?.motor_ids ?? []
  // Bench motors the scan did not hear: judged against the bench as it is
  // now, not as it was when the scan ran.
  const missing = scan ? motors.filter((m) => !found.includes(m.id)) : []
  const settled =
    scan !== null &&
    missing.length === 0 &&
    found.length === motors.length &&
    found.every((id) => numbers.has(id))

  useEffect(() => {
    if (scanning) setOpen(true)
  }, [scanning])
  useEffect(() => {
    if (scan === null) return
    setOpen(!settled)
  }, [scan, settled])
  const patchRow = (key: string, patch: Partial<Row>) =>
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const reprogram = (changes: { id: number; new_id: number; baud_rate: number }[], what: string) => {
    if (!window.confirm(`${what}\n\nThis writes the servos' EEPROM; the motors are released meanwhile.`)) return
    void call(() =>
      api.operationStart('motor_reprogram', {
        changes: changes.map((c) => ({ ...c, new_baud: BENCH_BAUD })),
      }),
    )
  }
  // Every bench motor to ID 30 + its number (slot 5 → ID 35).
  const shift = motors
    .map((m) => ({ id: m.id, new_id: ID_BASE + m.number, baud_rate: BENCH_BAUD, number: m.number }))
    .filter((c) => c.new_id !== c.id)
  let shiftBlocked: string | null = blocked
  if (!shiftBlocked && !bench) shiftBlocked = 'the config in force is a hand model'
  else if (!shiftBlocked && shift.length === 0) shiftBlocked = 'every motor already has ID 30 + its number'
  else if (!shiftBlocked && shift.some((c) => c.new_id > 252)) shiftBlocked = 'a motor number above 222 has no ID 30 + number'

  return (
    <section className="panel bench-bus">
      <div className="bench-bus-head">
        <button
          type="button"
          className="bench-bus-toggle"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          title={open ? 'fold the bus panel' : 'unfold the bus panel'}
        >
          <span className={`bench-chevron ${open ? 'open' : ''}`}>▸</span>
          <h2>Bus</h2>
        </button>
        <button
          className="btn btn-primary"
          disabled={busy || blocked !== null}
          title={
            blocked ??
            'ping ids 0–50 at 1 M baud (the motors are released and reconnected afterwards)'
          }
          onClick={() => void call(() => api.operationStart('bus_scan'))}
        >
          {scanning ? 'Scanning…' : 'Scan bus'}
        </button>
        <button
          className="btn btn-secondary"
          disabled={busy || blocked !== null}
          title={
            blocked ??
            'every ID 0–252 at every baud rate — finds a factory-new motor (ID 1 @ 57,600) or a stray ID; takes a minute or two'
          }
          onClick={() => void call(() => api.operationStart('bus_scan', { deep: true }))}
        >
          Deep scan
        </button>
        <button
          className="btn btn-secondary"
          disabled={busy || shiftBlocked !== null}
          title={
            shiftBlocked ??
            `re-program every bench motor to ID 30 + its number (${shift
              .slice(0, 4)
              .map((c) => `${c.id}→${c.new_id}`)
              .join(', ')}${shift.length > 4 ? ', …' : ''}), so the low IDs stay free for new motors`
          }
          onClick={() =>
            reprogram(
              shift,
              `Re-program ${shift.length} motor(s) to ID 30 + number:\n` +
                shift.map((c) => `motor ${c.number}: ID ${c.id} → ${c.new_id}`).join('\n'),
            )
          }
        >
          IDs → 30 + number
        </button>
        {programming && (
          <span className="bench-bus-progress">{operation?.detail ?? 're-programming…'}</span>
        )}
        {scanning && extra && (
          <span className="bench-bus-progress">
            {extra.motor_type} @ {extra.baud_rate ? baud(extra.baud_rate) : '?'} · id{' '}
            {Math.max(extra.scanned_to, 0)}/{extra.id_range[1]} ·{' '}
            {extra.motors.length} found
          </span>
        )}
        {!scanning && (
          <span className="bench-bus-summary">
            {scan && found.length === 0
              ? 'nothing answered — check motor power and the data cable'
              : motors.length
                ? motors.map((m) => `motor ${m.number} = id ${m.id}`).join(' · ')
                : 'no motors on the bench'}
            {scan && !settled && found.length > 0 && !open ? ' · scan differs — unfold to assign' : ''}
            {connected ? '' : ' · not connected'}
          </span>
        )}
      </div>

      {open && scanning && extra && extra.motors.length > 0 && (
        <div className="bench-bus-list">
          {extra.motors.map((m) => (
            <span key={`${m.id}-${m.baud_rate}`} className="bench-bus-chip">
              <b>ID {m.id}</b> {m.model_name} · {baud(m.baud_rate)}
            </span>
          ))}
        </div>
      )}

      {open && !scanning && scan && rows.length > 0 && (
        <div className="bench-assign">
          <table className="bench-assign-table">
            <thead>
              <tr>
                <th title="run this motor on the bench">use</th>
                <th>bus id</th>
                <th>model</th>
                <th>baud</th>
                <th title="what the bench calls it">motor number</th>
                <th>now</th>
                <th title="write a new ID into the servo (moved onto 1 M baud too)">re-program</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const current = numbers.get(row.id)
                const target = parseInt(row.newId, 10)
                const taken = rows.some((r) => r.id === target) || motors.some((m) => m.id === target)
                const programBlocked =
                  blocked ??
                  (!bench
                    ? 'the config in force is a hand model'
                    : !Number.isFinite(target) || target < 1 || target > 252
                      ? 'enter an ID of 1–252'
                      : taken
                        ? `ID ${target} is already on the bus`
                        : null)
                return (
                  <tr key={row.key} className={row.use ? '' : 'off'}>
                    <td>
                      <input
                        type="checkbox"
                        checked={row.use}
                        disabled={row.baud !== BENCH_BAUD}
                        title={row.baud !== BENCH_BAUD ? 'not at 1 M baud — re-program it first' : undefined}
                        onChange={(e) => patchRow(row.key, { use: e.target.checked })}
                      />
                    </td>
                    <td>
                      <b>ID {row.id}</b>
                    </td>
                    <td>{row.model}</td>
                    <td>{baud(row.baud)}</td>
                    <td>
                      motor{' '}
                      <input
                        type="number"
                        min={1}
                        step={1}
                        value={row.number}
                        disabled={!row.use}
                        onChange={(e) => patchRow(row.key, { number: e.target.value })}
                      />
                    </td>
                    <td className="bench-assign-now">
                      {current === undefined ? 'new' : `motor ${current}`}
                    </td>
                    <td className="bench-reprogram">
                      ID{' '}
                      <input
                        type="number"
                        min={1}
                        max={252}
                        placeholder={String(row.id)}
                        value={row.newId}
                        onChange={(e) => patchRow(row.key, { newId: e.target.value })}
                      />
                      <button
                        className="btn btn-secondary"
                        disabled={busy || programBlocked !== null}
                        title={programBlocked ?? `write ID ${target} into this servo, at 1 M baud`}
                        onClick={() =>
                          reprogram(
                            [{ id: row.id, new_id: target, baud_rate: row.baud }],
                            `Re-program ID ${row.id} (${baud(row.baud)}) → ID ${target} at 1M baud?`,
                          )
                        }
                      >
                        Write
                      </button>
                    </td>
                  </tr>
                )
              })}
              {missing.map((m) => (
                <tr key={`missing-${m.id}`} className="missing">
                  <td />
                  <td>
                    <b>ID {m.id}</b>
                  </td>
                  <td colSpan={2}>not answering</td>
                  <td>motor {m.number}</td>
                  <td className="bench-assign-now">dropped on apply</td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
          <div className="bench-assign-actions">
            <button
              className="btn btn-info"
              disabled={busy || blocked !== null || applyBlocked !== null}
              title={applyBlocked ?? blocked ?? 'rewrite the bench to these motors and reconnect'}
              onClick={() => void call(() => api.benchMotors(parsed))}
            >
              Use {picked.length} motor{picked.length === 1 ? '' : 's'} as numbered
            </button>
            <span className="bench-blocked">{applyBlocked ?? ''}</span>
          </div>
          {scan.mixed_baud && (
            <div className="bench-bus-note">
              Motors answer at {scan.baud_rates.map(baud).join(' and ')}. One bus runs at one
              rate — re-program the odd one out before using the set together.
            </div>
          )}
        </div>
      )}
    </section>
  )
}

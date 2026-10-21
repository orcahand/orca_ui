// Which motors are actually on the bus, and which of them the bench runs as
// what. A scan pings every ID at the family's baud rates (the session is
// closed for its duration). What answered is listed with a "use" box and a
// number per motor — the number is what the bench calls it, the id is the
// servo's — and Apply rewrites the bench config to that set and reconnects.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/rest'
import type { BusScanExtra, BusScanResult } from '../api/types'
import { useAppStore } from '../state/appStore'
import {
  isOperationActive,
  operationLabel,
  useOperationStore,
} from '../state/operationStore'
import { useBenchStore } from './benchStore'

interface Row {
  id: number
  model: string
  baud: number
  use: boolean
  number: string // text while editing
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
      return { id: m.id, model: m.model_name, baud: m.baud_rate, use: true, number: String(n) }
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
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<Row[]>([])
  // Folded by default; opens itself while scanning and when a scan has
  // something to decide, folds again once the bench matches the bus.
  const [open, setOpen] = useState(false)

  const active = isOperationActive(operation)
  const scanning = active && operation?.kind === 'bus_scan'
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
  const patchRow = (id: number, patch: Partial<Row>) =>
    setRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)))

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
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const current = numbers.get(row.id)
                return (
                  <tr key={row.id} className={row.use ? '' : 'off'}>
                    <td>
                      <input
                        type="checkbox"
                        checked={row.use}
                        onChange={(e) => patchRow(row.id, { use: e.target.checked })}
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
                        onChange={(e) => patchRow(row.id, { number: e.target.value })}
                      />
                    </td>
                    <td className="bench-assign-now">
                      {current === undefined ? 'new' : `motor ${current}`}
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

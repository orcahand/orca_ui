// Run control, plus the defaults a motor's cycle starts from. Each motor
// card carries its own cycle definition; "apply to all" stamps these onto
// every card. Everything the operation validates is gated here too, so the
// Start button says why it is off instead of bouncing a 409.

import { useMemo, useState } from 'react'
import { api } from '../api/rest'
import type { MotorCycleExtra } from '../api/types'
import { useAppStore } from '../state/appStore'
import {
  isOperationActive,
  operationLabel,
  useOperationStore,
} from '../state/operationStore'
import { runnableMotors, useBenchStore } from './benchStore'
import { CycleFields } from './CycleFields'

export function CyclePanel({ connected }: { connected: boolean }) {
  const settings = useBenchStore((s) => s.settings)
  const patchSettings = useBenchStore((s) => s.patchSettings)
  const applyToAll = useBenchStore((s) => s.applyToAll)
  // Derived outside the selector: a selector returning a fresh array every
  // call would re-render forever.
  const motors = useBenchStore((s) => s.motors)
  const setup = useBenchStore((s) => s.setup)
  const runnable = useMemo(() => runnableMotors(motors, setup), [motors, setup])
  const logCsv = useBenchStore((s) => s.logCsv)
  const setLogCsv = useBenchStore((s) => s.setLogCsv)
  const logPartMb = useBenchStore((s) => s.logPartMb)
  const setLogPartMb = useBenchStore((s) => s.setLogPartMb)
  const control = useAppStore((s) => s.control)
  const heldMotors = control?.held_motors ?? []
  const setError = useAppStore((s) => s.setError)
  const operation = useOperationStore((s) => s.operation)
  const [busy, setBusy] = useState(false)

  const active = isOperationActive(operation)
  const ours = active && operation?.kind === 'motor_cycle'
  const paused = ours && operation?.state === 'paused'
  // While a run is ours the backend's switch is the truth; the stored flag
  // is what the next run starts with.
  const log = ours ? ((operation?.extra as MotorCycleExtra | null)?.log ?? null) : null
  const logging = log ? log.on : logCsv

  let blocked: string | null = null
  if (!connected) blocked = 'no motor bus'
  else if (active) blocked = `${operationLabel(operation!.kind)} is running`
  else if (control && control.control_source !== 'manual')
    blocked = `control is owned by ${control.control_owner}`
  else if (runnable.length === 0) blocked = 'set A and B on at least one motor'
  else {
    const loose = runnable.filter((m) => !heldMotors.includes(m.id))
    if (loose.length > 0) {
      const names = loose.map((m) => motors.find((x) => x.id === m.id)?.number ?? m.id)
      blocked = `hold motor ${names.join(', ')} first`
    }
  }

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

  const start = () =>
    call(() =>
      api.operationStart('motor_cycle', {
        motors: runnable,
        log: logCsv,
        log_part_mb: logPartMb,
      }),
    )

  const toggleLog = () => {
    const next = !logging
    setLogCsv(next)
    if (ours) void call(() => api.operationInput(next ? 'log on' : 'log off'))
  }

  return (
    <section className="panel bench-cycle">
      <div className="panel-header">
        <h2>Run</h2>
        <span className="panel-hint">
          {runnable.length} motor{runnable.length === 1 ? '' : 's'} armed
          {runnable.length > 0 && ' · each on its own cycle'}
        </span>
      </div>

      <div className="bench-run-buttons">
        {!ours ? (
          <button
            className="btn btn-primary bench-start"
            disabled={busy || blocked !== null}
            title={blocked ?? 'start every armed motor on its own cycle'}
            onClick={() => void start()}
          >
            ▶ Start
          </button>
        ) : (
          <>
            <button
              className="btn btn-secondary"
              disabled={busy}
              onClick={() =>
                void call(() => (paused ? api.operationResume() : api.operationPause()))
              }
            >
              {paused ? '▶ Resume' : '❚❚ Pause'}
            </button>
            <button
              className="btn btn-danger"
              disabled={busy}
              onClick={() => void call(() => api.operationStop())}
            >
              ■ Stop
            </button>
          </>
        )}
        {blocked && !ours && <span className="bench-blocked">{blocked}</span>}
        <label
          className={`bench-log-toggle ${logging ? 'on' : ''}`}
          title={
            ours
              ? 'switch the CSV log on or off while the run goes on'
              : 'write every sample and every completed cycle of the run to a CSV'
          }
        >
          <input type="checkbox" checked={logging} disabled={busy} onChange={toggleLog} />
          Log CSV
          {log && log.rows > 0 && (
            <small>
              {log.rows.toLocaleString()} rows
              {log.files.length > 1 && ` · ${log.files.length} files`}
            </small>
          )}
        </label>
        <label
          className="bench-log-part"
          title="a new file is started once the current one reaches this size, so no single CSV outgrows a spreadsheet"
        >
          split at
          <input
            type="number"
            min={1}
            max={2000}
            step={10}
            value={logPartMb}
            disabled={ours}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10)
              if (Number.isFinite(v) && v >= 1 && v <= 2000) setLogPartMb(v)
            }}
          />
          MB
        </label>
      </div>

      <div className="bench-defaults">
        <div className="bench-defaults-head">
          <span>Cycle defaults</span>
          <button
            className="btn btn-secondary"
            disabled={ours || motors.length === 0}
            title="copy these onto every motor card (endpoints stay)"
            onClick={applyToAll}
          >
            Apply to all motors
          </button>
        </div>
        <CycleFields value={settings} onChange={patchSettings} disabled={ours} name="defaults" />
      </div>
    </section>
  )
}

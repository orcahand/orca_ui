// Testing tab (bare bench only): drive one motor with a chirp -- a sine whose
// frequency sweeps f0 -> f1 under a cosine ramp -- in position or current
// mode, watch command and response live, and keep the full-rate record as a
// CSV. Bench telemetry stands down while a run owns the bus.

import { useCallback, useEffect, useRef, useState } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { api } from '../../api/rest'
import type {
  TestingMode,
  TestingMotor,
  TestingRequest,
  TestingRun,
  TestingState,
} from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import type { LatestFrames } from '../../state/streamStore'
import { latest } from '../../state/streamStore'
import { usePalette } from '../../theme/themeStore'
import { Panel } from '../common/Panel'

const DEFAULTS: Omit<TestingRequest, 'motor_id' | 'mode' | 'amplitude'> = {
  f0_hz: 0.2,
  f1_hz: 5,
  duration_s: 10,
  offset: 0,
  centre_on_present: true,
  sweep: 'linear',
  taper: 'cosine',
  taper_s: 0.5,
  rate_hz: 200,
  torque_unit: 'ma',
  position_envelope_rad: 1,
  comment: '',
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null || Number.isNaN(v) ? '—' : v.toFixed(digits)

export function TestingView() {
  const status = useAppStore((s) => s.status)
  const setError = useAppStore((s) => s.setError)
  const bare = status?.bare ?? false

  const [motors, setMotors] = useState<TestingMotor[]>([])
  const [runs, setRuns] = useState<TestingRun[]>([])
  const [state, setState] = useState<TestingState | null>(null)
  const [busy, setBusy] = useState(false)

  const [motorId, setMotorId] = useState<number | null>(null)
  const [mode, setMode] = useState<TestingMode>('position')
  const [amplitude, setAmplitude] = useState('0.3')
  const [form, setForm] = useState({ ...DEFAULTS })
  const [offset, setOffset] = useState('0')
  const [taperS, setTaperS] = useState('0.5')
  const [comment, setComment] = useState('')

  const motor = motors.find((m) => m.id === motorId) ?? null
  const running = state?.status === 'running'

  const report = useCallback(
    (error: unknown) => setError(String((error as Error).message ?? error)),
    [setError],
  )

  const refreshRuns = useCallback(() => {
    api.testingRuns().then((r) => setRuns(r.runs)).catch(report)
  }, [report])

  useEffect(() => {
    if (!bare) return
    api
      .testingMotors()
      .then((r) => {
        setMotors(r.motors)
        setMotorId((id) => id ?? r.motors[0]?.id ?? null)
      })
      .catch(report)
    api.testingState().then(setState).catch(() => undefined)
    refreshRuns()
  }, [bare, report, refreshRuns])

  // Run state arrives on the stream; mirror it into React state (it changes
  // at most ~30 Hz) and refresh the run list when a run finishes.
  const lastStatus = useRef<string | null>(null)
  useStreamFrame((frames: LatestFrames) => {
    const next = frames.testing.state
    if (!next || next === state) return
    setState(next)
    if (lastStatus.current === 'running' && next.status !== 'running') {
      refreshRuns()
    }
    lastStatus.current = next.status
  })

  // A motor with no current control (or no torque curve) narrows the form.
  useEffect(() => {
    if (motor && !motor.current_control && mode === 'current') setMode('position')
    if (motor && !motor.torque_curve && form.torque_unit === 'nm') {
      setForm((f) => ({ ...f, torque_unit: 'ma' }))
    }
  }, [motor, mode, form.torque_unit])

  const start = async () => {
    if (motorId == null) return
    setBusy(true)
    try {
      const body: TestingRequest = {
        ...form,
        motor_id: motorId,
        mode,
        amplitude: Number(amplitude),
        offset: Number(offset) || 0,
        taper_s: form.taper === 'none' ? 0 : Number(taperS) || 0,
        comment: comment.trim(),
      }
      const next = await api.testingStart(body)
      setComment('')
      latest.testing.trace = []
      setState(next)
      setError(null)
    } catch (error) {
      report(error)
    } finally {
      setBusy(false)
    }
  }

  const stop = () => api.testingStop().catch(report)

  const remove = async (runId: string) => {
    try {
      await api.testingRunDelete(runId)
      refreshRuns()
    } catch (error) {
      report(error)
    }
  }

  if (!bare) {
    return (
      <Panel title="Testing">
        <p className="panel-hint">
          Excitation tests are a bare-bench control: on an assembled hand a
          chirp on one motor pulls on every tendon it shares. Start the console
          in bare motor mode to use this tab.
        </p>
      </Panel>
    )
  }

  const amplitudeUnit =
    mode === 'position' ? 'rad' : form.torque_unit === 'nm' ? 'N·m' : 'mA'
  const num = (key: keyof typeof form, width = 56, step = 0.1, min?: number) => (
    <input
      type="number"
      step={step}
      min={min}
      value={form[key] as number}
      onChange={(e) => setForm((f) => ({ ...f, [key]: Number(e.target.value) }))}
      style={{ width }}
      disabled={running}
    />
  )

  return (
    <>
      <Panel
        title="Chirp Excitation"
        toolbar={
          running ? (
            <button className="btn btn-danger" onClick={stop}>
              stop
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={busy || motorId == null || !(Number(amplitude) > 0)}
              onClick={start}
            >
              start
            </button>
          )
        }
      >
        {motors.length === 0 ? (
          <p className="panel-hint">no motors on the bus</p>
        ) : (
          <div
            style={{
              display: 'flex',
              gap: 14,
              alignItems: 'center',
              flexWrap: 'wrap',
              color: 'var(--dim)',
              fontSize: 12,
            }}
          >
            <label>
              motor{' '}
              <select
                value={motorId ?? ''}
                onChange={(e) => setMotorId(Number(e.target.value))}
                disabled={running}
              >
                {motors.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                    {m.model?.label ? ` · ${m.model.label}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label title="position: goal positions about a centre. current: a signed goal current, which needs a motor family with a current-control mode">
              mode{' '}
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as TestingMode)}
                disabled={running}
              >
                <option value="position">position</option>
                <option value="current" disabled={!motor?.current_control}>
                  current{motor && !motor.current_control ? ' (not on this motor)' : ''}
                </option>
              </select>
            </label>
            <label title="peak deviation from the centre (position) or from the bias (current)">
              amplitude{' '}
              <input
                type="number"
                step={mode === 'position' ? 0.05 : form.torque_unit === 'nm' ? 0.05 : 10}
                min={0}
                value={amplitude}
                onChange={(e) => setAmplitude(e.target.value)}
                style={{ width: 64 }}
                disabled={running}
              />{' '}
              {mode === 'current' ? (
                <select
                  value={form.torque_unit}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, torque_unit: e.target.value as 'ma' | 'nm' }))
                  }
                  disabled={running}
                  title="N·m is translated to current through the motor model's fitted torque curve"
                >
                  <option value="ma">mA</option>
                  <option value="nm" disabled={!motor?.torque_curve}>
                    N·m
                  </option>
                </select>
              ) : (
                amplitudeUnit
              )}
            </label>
            <label title="sweep from f0 to f1 over the run">
              f0 {num('f0_hz', 52, 0.1, 0.01)} → f1 {num('f1_hz', 52, 0.5, 0.01)} Hz
            </label>
            <label>
              <select
                value={form.sweep}
                onChange={(e) =>
                  setForm((f) => ({ ...f, sweep: e.target.value as 'linear' | 'exponential' }))
                }
                disabled={running}
              >
                <option value="linear">linear sweep</option>
                <option value="exponential">exponential sweep</option>
              </select>
            </label>
            <label>duration {num('duration_s', 52, 1, 0.5)} s</label>
            <label title="cosine ramp at both ends so the motor is never stepped">
              <select
                value={form.taper}
                onChange={(e) =>
                  setForm((f) => ({ ...f, taper: e.target.value as 'cosine' | 'none' }))
                }
                disabled={running}
              >
                <option value="cosine">cosine ramp</option>
                <option value="none">no ramp</option>
              </select>{' '}
              {form.taper === 'cosine' && (
                <>
                  <input
                    type="number"
                    step={0.1}
                    min={0}
                    value={taperS}
                    onChange={(e) => setTaperS(e.target.value)}
                    style={{ width: 48 }}
                    disabled={running}
                  />{' '}
                  s
                </>
              )}
            </label>
            <label title="command-and-sample rate; the bus round trip caps what is achieved">
              rate {num('rate_hz', 56, 10, 20)} Hz
            </label>
            {mode === 'position' ? (
              <label title="chirp about the present position, or about a fixed centre in radians">
                <input
                  type="checkbox"
                  checked={form.centre_on_present}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, centre_on_present: e.target.checked }))
                  }
                  disabled={running}
                />{' '}
                centre on present
                {!form.centre_on_present && (
                  <>
                    {' '}
                    <input
                      type="number"
                      step={0.05}
                      value={offset}
                      onChange={(e) => setOffset(e.target.value)}
                      style={{ width: 64 }}
                      disabled={running}
                    />{' '}
                    rad
                  </>
                )}
              </label>
            ) : (
              <>
                <label title="constant current added to the chirp">
                  bias{' '}
                  <input
                    type="number"
                    step={10}
                    value={offset}
                    onChange={(e) => setOffset(e.target.value)}
                    style={{ width: 56 }}
                    disabled={running}
                  />{' '}
                  mA
                </label>
                <label title="the run aborts and unloads the motor if it travels this far from where it started">
                  envelope {num('position_envelope_rad', 48, 0.1, 0.05)} rad
                </label>
              </>
            )}
            <label
              title="written as a '#' line under the CSV header and into the JSON sidecar"
              style={{ flexBasis: '100%' }}
            >
              comment{' '}
              <input
                type="text"
                maxLength={500}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="what this run is (load, setup, purpose)"
                disabled={running}
                style={{ width: 'min(520px, 80%)' }}
              />
            </label>
            {motor && (
              <span style={{ color: 'var(--dimmer)', fontSize: 11 }}>
                {motor.range_rad
                  ? `range ${fmt(motor.range_rad[0])}..${fmt(motor.range_rad[1])} rad`
                  : 'no range recorded'}
                {motor.ceiling_ma != null && ` · ceiling ${motor.ceiling_ma.toFixed(0)} mA`}
              </span>
            )}
          </div>
        )}
        <RunStatus state={state} />
      </Panel>

      <Panel title="Trace">
        <TracePlot mode={state?.spec?.mode ?? mode} />
      </Panel>

      <Panel
        title="Recordings"
        toolbar={
          <button className="btn btn-secondary" onClick={refreshRuns}>
            refresh
          </button>
        }
      >
        {runs.length === 0 ? (
          <p className="panel-hint">
            no recordings yet — each run is saved as a CSV (t, command, position,
            velocity, current) with a JSON sidecar under the library&apos;s
            motortestingdata folder
          </p>
        ) : (
          <table className="motor-table">
            <thead>
              <tr>
                <th>run</th>
                <th>motor</th>
                <th>mode</th>
                <th>amplitude</th>
                <th>f0→f1</th>
                <th>samples</th>
                <th>rate</th>
                <th>status</th>
                <th>comment</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td style={{ fontFamily: 'Space Mono, monospace' }}>{run.run_id}</td>
                  <td>{run.spec.motor_id}</td>
                  <td>{run.spec.mode}</td>
                  <td>
                    {run.spec.amplitude}{' '}
                    {run.spec.mode === 'position'
                      ? 'rad'
                      : run.spec.torque_unit === 'nm'
                        ? 'N·m'
                        : 'mA'}
                  </td>
                  <td>
                    {run.spec.f0_hz}→{run.spec.f1_hz} Hz
                  </td>
                  <td>{run.samples}</td>
                  <td>{fmt(run.achieved_rate_hz, 0)} Hz</td>
                  <td title={run.detail}>{run.status}</td>
                  <td style={{ maxWidth: 260, whiteSpace: 'nowrap', overflow: 'hidden',
                               textOverflow: 'ellipsis' }} title={run.comment ?? ''}>
                    {run.comment ?? ''}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <a
                      className="btn btn-secondary"
                      href={api.testingRunCsvUrl(run.run_id)}
                      download={run.csv}
                    >
                      csv
                    </a>{' '}
                    <button className="btn btn-secondary" onClick={() => remove(run.run_id)}>
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  )
}

function RunStatus({ state }: { state: TestingState | null }) {
  if (!state || state.status === 'idle') return null
  const color =
    state.status === 'error'
      ? 'var(--danger, #f87171)'
      : state.status === 'running'
        ? 'var(--accent)'
        : 'var(--dim)'
  return (
    <div style={{ marginTop: 8, fontSize: 12, color }}>
      <strong>{state.status}</strong>
      {state.status === 'running' && ` · ${Math.round(state.progress * 100)}%`}
      {state.detail && ` · ${state.detail}`}
      {state.samples > 0 && ` · ${state.samples} samples`}
      {state.achieved_rate_hz != null && ` @ ${state.achieved_rate_hz.toFixed(0)} Hz`}
      {state.spec?.torque_extrapolated && (
        <span style={{ color: 'var(--warn)' }}>
          {' '}
          · amplitude lies outside the fitted torque curve; current was clamped
          to the curve&apos;s end
        </span>
      )}
      {state.spec?.amplitude_ma != null && state.spec.mode === 'current' && (
        <span style={{ color: 'var(--dimmer)' }}>
          {' '}
          · {state.spec.amplitude_ma.toFixed(0)} mA peak
        </span>
      )}
    </div>
  )
}

// Command and response of the current run against time. The y-axes are the
// command's own unit on the left (rad or mA) and current on the right.
function TracePlot({ mode }: { mode: TestingMode }) {
  const { chart, accent, purple, warn } = usePalette()
  const hostRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const axisFont = `9px 'Space Mono'`
    const axis = (extra: Partial<uPlot.Axis>): uPlot.Axis => ({
      stroke: chart.axis,
      grid: { stroke: chart.grid, width: 1 },
      ticks: { stroke: chart.ticks },
      font: axisFont,
      ...extra,
    })
    const plot = new uPlot(
      {
        width: host.clientWidth || 720,
        height: 260,
        padding: [8, 8, 0, 0],
        cursor: { show: true },
        legend: { show: true },
        scales: {
          x: { time: false },
          y: {},
          cur: {},
        },
        axes: [
          axis({ size: 26, values: (_u, t) => t.map((v) => `${v.toFixed(1)}s`) }),
          axis({
            scale: 'y',
            size: 48,
            values: (_u, t) => t.map((v) => v.toFixed(mode === 'position' ? 2 : 0)),
          }),
          axis({
            scale: 'cur',
            side: 1,
            size: 48,
            grid: { show: false },
            values: (_u, t) => t.map((v) => `${v.toFixed(0)}mA`),
          }),
        ],
        series: [
          { label: 't' },
          {
            label: mode === 'position' ? 'command rad' : 'command mA',
            scale: mode === 'position' ? 'y' : 'cur',
            stroke: purple,
            width: 1.25,
            points: { show: false },
          },
          {
            label: 'position rad',
            scale: mode === 'position' ? 'y' : 'y',
            stroke: accent,
            width: 1.25,
            points: { show: false },
          },
          {
            label: 'current mA',
            scale: 'cur',
            stroke: warn,
            width: 1,
            points: { show: false },
          },
        ],
      },
      [[], [], [], []],
      host,
    )
    plotRef.current = plot
    const onResize = () => plot.setSize({ width: host.clientWidth || 720, height: 260 })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      plotRef.current = null
      plot.destroy()
    }
  }, [chart, accent, purple, warn, mode])

  const drawn = useRef(0)
  useStreamFrame((frames) => {
    const plot = plotRef.current
    const trace = frames.testing.trace
    if (!plot) return
    if (trace.length === drawn.current && trace.length !== 0) return
    drawn.current = trace.length
    plot.setData([
      trace.map((s) => s.t),
      trace.map((s) => s.cmd),
      trace.map((s) => s.pos),
      trace.map((s) => s.cur),
    ])
  })

  return <div ref={hostRef} />
}

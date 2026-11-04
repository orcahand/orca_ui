// The motor testbench page: a few motors on a bus, no hand around them.
// Three modes, switched in the header: *cycle* — hold them (torque), jog
// them to tension a tendon, capture each motor's range by moving it by hand,
// then cycle the range and watch the numbers — *thermal* — clamp the shafts,
// drive a current waveform into the motors and record their temperature —
// and *fingers* — mount a hand: tendons onto motors, the coupling between
// tendons and joints, each joint's range, then drive the joints. Same backend, same
// gates, same e-stop as the console — just the controls a bench needs, on
// one screen.

import { useEffect, useState } from 'react'
import { api } from '../api/rest'
import { startStreamClient, subscribeTopic } from '../api/streamClient'
import { TOPICS, type HandState } from '../api/types'
import { ErrorBanner } from '../components/common/ErrorBanner'
import { FingerWorkflow } from '../fingers/FingerWorkflow'
import { useFingerStore } from '../fingers/fingerStore'
import { EStopButton } from '../components/header/EStopButton'
import { ThemeToggle } from '../components/header/ThemeToggle'
import { useAppStore } from '../state/appStore'
import { useOperationStore } from '../state/operationStore'
import { ThermalMotors } from '../thermal/ThermalMotors'
import { ThermalRun } from '../thermal/ThermalRun'
import { ThermalSetup } from '../thermal/ThermalSetup'
import { useThermalStore } from '../thermal/thermalStore'
import { type BenchMode, useBenchStore } from './benchStore'
import { BenchLog } from './BenchLog'
import { BusPanel } from './BusPanel'
import { CyclePanel } from './CyclePanel'
import { MotorCard } from './MotorCard'
import { RunPanel } from './RunPanel'
import { TorqueBar } from './TorqueBar'
import { UsbIndicator } from './UsbIndicator'

const STATE_CLASS: Record<HandState, string> = {
  connected: 'connected',
  degraded: 'busy',
  detecting: 'busy',
  connecting: 'busy',
  reconnecting: 'busy',
  maintenance: 'maintenance',
  disconnected: 'disconnected',
}

const STATE_LABEL: Record<HandState, string> = {
  connected: 'Connected',
  degraded: 'Degraded',
  detecting: 'Searching…',
  connecting: 'Connecting…',
  reconnecting: 'Reconnecting…',
  maintenance: 'Maintenance',
  disconnected: 'Disconnected',
}

const MODES: { mode: BenchMode; label: string; title: string; kind: string }[] = [
  {
    mode: 'cycle',
    label: 'Cycle',
    title: 'tension and cycle tendons: hold, jog, capture a range, cycle it',
    kind: 'motor_cycle',
  },
  {
    mode: 'thermal',
    label: 'Thermal',
    title: 'thermal test: clamp the shafts, drive a current waveform, record the temperature',
    kind: 'motor_thermal',
  },
  {
    mode: 'fingers',
    label: 'Fingers',
    title: 'fingers on the motors: name the joints, capture their ends, drive them from sliders',
    kind: 'finger_control',
  },
]

export function BenchApp() {
  const status = useAppStore((s) => s.status)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const handInfo = useAppStore((s) => s.handInfo)
  const poseSource = useAppStore((s) => s.control?.pose_source ?? null)
  const motors = useBenchStore((s) => s.motors)
  const model = useBenchStore((s) => s.model)
  const adoptHand = useBenchStore((s) => s.adoptHand)
  const mode = useBenchStore((s) => s.mode)
  const setMode = useBenchStore((s) => s.setMode)
  const adoptThermal = useThermalStore((s) => s.adopt)
  const adoptFingers = useFingerStore((s) => s.adopt)
  const thermalFree = useThermalStore((s) => s.settings.load === 'free')
  const setError = useAppStore((s) => s.setError)
  const [quitting, setQuitting] = useState(false)
  const runningKind = useOperationStore((s) =>
    s.operation && s.operation.state !== 'done' && s.operation.state !== 'error'
      ? s.operation.kind
      : null,
  )

  useEffect(() => {
    startStreamClient()
    subscribeTopic(TOPICS.motorsState)
    subscribeTopic(TOPICS.usbPresence)
    api.status().then(useAppStore.getState().setStatus).catch(() => undefined)
    api.handInfo().then(useAppStore.getState().setHandInfo).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (handInfo) adoptHand(handInfo)
  }, [handInfo, adoptHand])
  useEffect(() => {
    if (model) {
      adoptThermal(model, motors)
      adoptFingers(model, motors)
    }
  }, [model, motors, adoptThermal, adoptFingers])

  // A run in progress decides the mode: opening the page mid-run lands on
  // the panels that show it.
  useEffect(() => {
    if (runningKind === 'motor_thermal') setMode('thermal')
    else if (runningKind === 'motor_cycle') setMode('cycle')
    else if (runningKind === 'finger_control') setMode('fingers')
  }, [runningKind, setMode])

  // The console stops reading the motors once torque is on (commands and
  // reads share the bus). The bench wants the shaft position at all times —
  // that is how a range is captured — so pin the estimate source. Two
  // motors are a light load; a hand's 17 would be the console's call.
  useEffect(() => {
    if (wsConnected && poseSource !== null && poseSource !== 'estimate') {
      api.setPoseSource('estimate').catch(() => undefined)
    }
  }, [wsConnected, poseSource])

  const state: HandState = !wsConnected ? 'disconnected' : (status?.state ?? 'detecting')
  const port = status?.ports?.motor ?? null
  const connected = wsConnected && (state === 'connected' || state === 'degraded')

  return (
    <div className="container bench">
      <header>
        <h1 className="brand">
          <span className="brand-mark">◈ ORCA</span>
          <span className="brand-sub">MOTOR BENCH</span>
        </h1>
        <div className="bench-mode-switch" role="tablist" aria-label="bench mode">
          {MODES.map(({ mode: m, label, title, kind }) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              className={`bench-mode-tab ${mode === m ? 'on' : ''}`}
              title={title}
              onClick={() => setMode(m)}
            >
              {label}
              {runningKind === kind && <i className="bench-mode-live" aria-label="running" />}
            </button>
          ))}
        </div>
        <UsbIndicator connected={connected} />
        <span
          className={`status-indicator ${STATE_CLASS[state] ?? 'busy'}`}
          title={status?.message ?? ''}
        >
          {wsConnected ? STATE_LABEL[state] ?? state : 'Backend offline'}
        </span>
        {status?.model && (
          <span className="capability-badge" title={port ?? 'motor port not resolved'}>
            {status.model}
            {port ? ` · ${port}` : ''}
          </span>
        )}
        <div className="header-spacer" />
        <a
          className="btn btn-secondary bench-console-link"
          href="/console"
          title="the full hand console, on the same backend"
        >
          Full console
        </a>
        <ThemeToggle />
        <button
          className="btn btn-secondary bench-quit"
          disabled={!wsConnected || quitting || runningKind !== null}
          title={
            runningKind !== null
              ? 'a run is in progress — stop it first'
              : 'stop the backend (same as Ctrl+C in the terminal); closing the tab does this too after a few seconds'
          }
          onClick={() => {
            if (!window.confirm('Stop the backend? The motors are released.')) return
            setQuitting(true)
            api.quit().catch((error) => {
              setError(String((error as Error).message ?? error))
              setQuitting(false)
            })
          }}
        >
          {quitting ? 'stopping…' : '⏻ Quit'}
        </button>
        <EStopButton />
      </header>
      <ErrorBanner />
      <TorqueBar
        connected={connected}
        heldHint={
          mode === 'thermal'
            ? thermalFree
              ? 'all held — set the waveform, Start; the motors will turn'
              : 'all held — clamp the shafts, set the waveform, Start'
            : mode === 'fingers'
              ? 'all held — in Control, Engage to drive the joints'
              : 'all held — jog to tension, Start to cycle'
        }
      />
      <BusPanel connected={connected} />
      {mode === 'fingers' ? (
        <FingerWorkflow connected={connected} />
      ) : mode === 'thermal' ? (
        <>
          <ThermalMotors connected={connected} />
          <div className="bench-main thermal-main">
            <ThermalSetup connected={connected} />
            <ThermalRun />
          </div>
        </>
      ) : (
        <>
          {motors.length === 0 ? (
            <section className="panel panel-empty">
              {connected
                ? 'The connected config names no motors.'
                : 'Waiting for the motor bus… power the motors, plug in the adapter, or scan to see what answers.'}
            </section>
          ) : (
            <div className="bench-motors" style={{ '--count': motors.length } as React.CSSProperties}>
              {motors.map((motor) => (
                <MotorCard key={motor.id} motor={motor} connected={connected} />
              ))}
            </div>
          )}
          <div className="bench-main">
            <CyclePanel connected={connected} />
            <RunPanel />
          </div>
        </>
      )}
      <BenchLog />
    </div>
  )
}

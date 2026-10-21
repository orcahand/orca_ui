// The motor testbench page: a few motors on a bus, no hand around them.
// Hold them (torque), jog them to tension a tendon, capture each motor's
// range by moving it by hand, then cycle the range and watch the numbers.
// Same backend, same gates, same e-stop as the console — just the controls
// a bench needs, on one screen.

import { useEffect } from 'react'
import { api } from '../api/rest'
import { startStreamClient, subscribeTopic } from '../api/streamClient'
import { TOPICS, type HandState } from '../api/types'
import { ErrorBanner } from '../components/common/ErrorBanner'
import { EStopButton } from '../components/header/EStopButton'
import { ThemeToggle } from '../components/header/ThemeToggle'
import { useAppStore } from '../state/appStore'
import { useBenchStore } from './benchStore'
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

export function BenchApp() {
  const status = useAppStore((s) => s.status)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const handInfo = useAppStore((s) => s.handInfo)
  const poseSource = useAppStore((s) => s.control?.pose_source ?? null)
  const motors = useBenchStore((s) => s.motors)
  const adoptHand = useBenchStore((s) => s.adoptHand)

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
        <EStopButton />
      </header>
      <ErrorBanner />
      <TorqueBar connected={connected} />
      <BusPanel connected={connected} />
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
      <BenchLog />
    </div>
  )
}

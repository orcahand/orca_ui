// Boot-screen hero: fills the content area while the backend is offline or
// the connection ladder hasn't produced a session yet (disconnected /
// detecting / connecting). Maintenance and reconnecting keep the normal
// views — an established session exists conceptually there.

import { useEffect, useState } from 'react'
import { api } from '../api/rest'
import type { PortInfo } from '../api/types'
import { useAppStore } from '../state/appStore'

const PORT_KIND_BY_ITEM: Record<string, string[]> = {
  MOTORS: ['dynamixel', 'feetech'],
  ENCODERS: ['oh_board'],
  TACTILE: ['tactile_sensor'],
}

export function BootHero() {
  const wsConnected = useAppStore((s) => s.wsConnected)
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const [ports, setPorts] = useState<PortInfo[]>([])

  // Poll the port list while searching so the checklist can name the buses
  // it sees even before a session claims them.
  useEffect(() => {
    if (!wsConnected) return
    let cancelled = false
    const fetchPorts = () => {
      api
        .ports()
        .then((list) => {
          if (!cancelled) setPorts(list)
        })
        .catch(() => undefined)
    }
    fetchPorts()
    const timer = setInterval(fetchPorts, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [wsConnected])

  const caps = status?.capabilities
  const statusLine = !wsConnected
    ? 'BACKEND OFFLINE'
    : status?.state === 'connecting'
      ? 'CONNECTING …'
      : 'SEARCHING FOR HARDWARE …'

  const portFor = (item: string): PortInfo | undefined =>
    ports.find((p) => p.kind !== null && PORT_KIND_BY_ITEM[item].includes(p.kind))

  const items = [
    { label: 'MOTORS', on: caps?.motors ?? false, port: portFor('MOTORS') },
    { label: 'ENCODERS', on: caps?.encoders ?? false, port: portFor('ENCODERS') },
    { label: 'TACTILE', on: caps?.tactile ?? false, port: portFor('TACTILE') },
  ]

  return (
    <div className="boot-hero">
      <div className="boot-wordmark">◈ ORCA</div>
      <div className="boot-subtitle">HAND CONTROL CONSOLE</div>
      <div className={`boot-status ${wsConnected ? '' : 'offline'}`}>
        {statusLine}
      </div>
      {wsConnected && status?.message ? (
        <div className="boot-message">{status.message}</div>
      ) : null}
      {wsConnected && (
        <ul className="boot-checklist">
          {items.map((item) => (
            <li
              key={item.label}
              className={`boot-check-item ${item.on ? 'ok' : 'pending'}`}
            >
              <span className="boot-check-mark">{item.on ? '✓' : '·'}</span>
              <span>{item.label}</span>
              {item.port && (
                <span className="boot-check-port">{item.port.device}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="boot-footer">
        {handInfo ? `${handInfo.model_name} · ` : ''}orca-ui
      </div>
    </div>
  )
}

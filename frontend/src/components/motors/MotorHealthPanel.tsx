// Per-motor health table from the 1 Hz motors.telemetry topic (flows through
// the rAF stream store; a JSON compare keeps React renders at telemetry rate).

import { useMemo, useRef, useState } from 'react'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'

const TEMP_WARN_C = 55
const TEMP_ERR_C = 65
// Current tint kicks in near the configured max_current ceiling.
const CURRENT_WARN_FRACTION = 0.8

interface MotorRow {
  id: string
  temp: number | null
  current: number | null
}

function buildRows(
  temps: Record<string, number>,
  currents: Record<string, number>,
): MotorRow[] {
  const ids = Array.from(
    new Set([...Object.keys(temps), ...Object.keys(currents)]),
  ).sort((a, b) => Number(a) - Number(b))
  return ids.map((id) => ({
    id,
    temp: temps[id] ?? null,
    current: currents[id] ?? null,
  }))
}

export function MotorHealthPanel() {
  const maxCurrent = useAppStore((s) => s.control?.max_current ?? null)
  const joints = useAppStore((s) => s.handInfo?.joints)
  const [rows, setRows] = useState<MotorRow[]>([])
  const lastJson = useRef('')

  // Telemetry is keyed by motor id; a hot motor is only actionable once you
  // know which joint it drives.
  const jointOfMotor = useMemo(() => {
    const map = new Map<string, string>()
    for (const joint of joints ?? []) {
      if (joint.motor_id !== null && joint.motor_id !== undefined) {
        map.set(String(joint.motor_id), joint.id)
      }
    }
    return map
  }, [joints])

  useStreamFrame((frames) => {
    const next = buildRows(frames.motors.temps, frames.motors.currents)
    const json = JSON.stringify(next)
    if (json !== lastJson.current) {
      lastJson.current = json
      setRows(next)
    }
  })

  const tempClass = (temp: number | null): string => {
    if (temp === null) return ''
    if (temp >= TEMP_ERR_C) return 'err'
    if (temp >= TEMP_WARN_C) return 'warn'
    return ''
  }

  const currentClass = (current: number | null): string => {
    if (current === null || maxCurrent === null || maxCurrent <= 0) return ''
    const load = Math.abs(current) / maxCurrent
    if (load >= 1) return 'err'
    if (load >= CURRENT_WARN_FRACTION) return 'warn'
    return ''
  }

  return (
    <Panel title="Motor Health">
      {rows.length === 0 ? (
        <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
          no motor telemetry yet — appears at 1 Hz once motors are connected
        </div>
      ) : (
        <table className="motor-table">
          <thead>
            <tr>
              <th>MOTOR</th>
              <th>JOINT</th>
              <th>TEMP °C</th>
              <th>CURRENT mA</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td className="motor-joint">
                  {jointOfMotor.get(row.id) ?? '--'}
                </td>
                <td className={tempClass(row.temp)}>
                  {row.temp === null ? '--' : row.temp.toFixed(1)}
                </td>
                <td className={currentClass(row.current)}>
                  {row.current === null ? '--' : row.current.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

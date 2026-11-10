// Live readings a test step asks for while it is open. Motor readings come
// from the shared stream store; encoders, tactile and the operation log reuse
// the console's own panels.

import { useRef, useState } from 'react'
import type { HwPanel } from '../../api/hardwareTests'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { EncoderPanel } from '../encoders/EncoderPanel'
import { currentClass, tempClass } from '../motors/motorIssueRules'
import { OperationLogPane } from '../setup/OperationLogPane'
import { TactilePanel } from '../tactile/TactilePanel'

const MOTOR_PANELS: HwPanel[] = ['motor_positions', 'motor_currents', 'motor_temperatures']
const REFRESH_MS = 200
// Rated max operating temperature fallback until telemetry carries the family's value.
const DEFAULT_MAX_TEMP_C = 70

interface MotorRow {
  joint: string
  motor: number | null
  estimate: number | null
  measured: number | null
  current: number | null
  temp: number | null
}

interface MotorSnapshot {
  rows: MotorRow[]
  maxTempC: number
  ageS: number | null
}

function MotorReadings({ panels }: { panels: HwPanel[] }) {
  const joints = useAppStore((s) => s.handInfo?.joints ?? null)
  const maxCurrent = useAppStore((s) => s.control?.max_current ?? null)
  const [snapshot, setSnapshot] = useState<MotorSnapshot | null>(null)
  const lastAt = useRef(0)

  useStreamFrame((frames) => {
    const now = performance.now()
    if (now - lastAt.current < REFRESH_MS || !joints) return
    lastAt.current = now
    const { motors } = frames
    const rows = joints.map((joint) => {
      const key = joint.motor_id === null ? null : String(joint.motor_id)
      return {
        joint: joint.id,
        motor: joint.motor_id,
        estimate: frames.joints.estimate[joint.id] ?? null,
        measured: frames.joints.measured[joint.id] ?? null,
        current: key === null ? null : (motors.currents[key] ?? null),
        temp: key === null ? null : (motors.temps[key] ?? null),
      }
    })
    const tLatest = frames.joints.tMeasured
    setSnapshot({
      rows,
      maxTempC: motors.maxTempC ?? DEFAULT_MAX_TEMP_C,
      ageS: tLatest > 0 ? (Date.now() - tLatest) / 1000 : null,
    })
  })

  const showPosition = panels.includes('motor_positions')
  const showCurrent = panels.includes('motor_currents')
  const showTemp = panels.includes('motor_temperatures')
  const title = [showPosition && 'positions', showCurrent && 'currents', showTemp && 'temperatures']
    .filter(Boolean)
    .join(' · ')

  if (!joints) {
    return (
      <Panel title={`Motor ${title}`}>
        <div className="panel-empty">no hand session: readings appear once the hand connects</div>
      </Panel>
    )
  }
  const hasEncoders = snapshot?.rows.some((row) => row.measured !== null) ?? false
  const fmt = (value: number | null, digits = 1) => (value === null ? '—' : value.toFixed(digits))

  return (
    <Panel title={`Motor ${title}`}>
      {!snapshot ? (
        <div className="panel-empty">waiting for telemetry…</div>
      ) : (
        <table className="motor-table hwt-live-table">
          <thead>
            <tr>
              <th>JOINT</th>
              <th>MOTOR</th>
              {showPosition && <th title="joint angle derived from the motor">POS °</th>}
              {showPosition && hasEncoders && <th title="joint encoder">ENC °</th>}
              {showCurrent && <th>mA</th>}
              {showTemp && <th>°C</th>}
            </tr>
          </thead>
          <tbody>
            {snapshot.rows.map((row) => (
              <tr key={row.joint}>
                <td>{row.joint}</td>
                <td className="motor-joint">{row.motor ?? '—'}</td>
                {showPosition && <td>{fmt(row.estimate)}</td>}
                {showPosition && hasEncoders && <td>{fmt(row.measured)}</td>}
                {showCurrent && (
                  <td className={currentClass(row.current, maxCurrent)}>{fmt(row.current, 0)}</td>
                )}
                {showTemp && (
                  <td className={tempClass(row.temp, snapshot.maxTempC)}>{fmt(row.temp, 0)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {snapshot?.ageS !== null && snapshot !== null && hasEncoders && snapshot.ageS > 2 && (
        <div className="hwt-hint warn">encoder readings are {snapshot.ageS.toFixed(0)} s old</div>
      )}
      {(showCurrent || showTemp) && (
        <div className="hwt-hint">Currents and temperatures refresh about once a second.</div>
      )}
    </Panel>
  )
}

export function LivePanels({ panels }: { panels: HwPanel[] }) {
  if (panels.length === 0) return null
  const motorPanels = panels.filter((panel) => MOTOR_PANELS.includes(panel))
  return (
    <div className="hwt-live">
      {motorPanels.length > 0 && <MotorReadings panels={motorPanels} />}
      {panels.includes('joint_encoders') && <EncoderPanel />}
      {panels.includes('tactile') && <TactilePanel />}
      {panels.includes('operation_log') && <OperationLogPane />}
    </div>
  )
}

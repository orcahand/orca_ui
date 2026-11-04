// Step 1 — tendons: which motor each tendon is wound on. One row per
// tendon with the live shaft reading, a hold switch and jog buttons, so a
// motor can be turned to see which tendon it pulls before it is named.

import { useRef, useState } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'
import { useOperationActive } from '../state/operationStore'
import { type BenchMotor, useBenchStore } from '../bench/benchStore'
import { JOG_STEPS_DEG, useJog } from '../bench/useJog'
import { formatDeg, useMotorLive } from '../bench/useMotorLive'
import { type FingerTendon, useFingerStore } from './fingerStore'

const JOG_STEP_DEG = JOG_STEPS_DEG[1]

export function motorLabel(motors: BenchMotor[], id: number | null): string {
  if (id === null) return 'no motor'
  const motor = motors.find((m) => m.id === id)
  return motor ? `motor ${motor.number}` : `id ${id}`
}

// Hold / release and jog one motor; shared by the tendon and the range rows.
export function MotorHandles({ motorId, connected }: { motorId: number | null; connected: boolean }) {
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const [busy, setBusy] = useState(false)
  const livePos = useRef<number | null>(null)
  const held = motorId !== null && (control?.held_motors?.includes(motorId) ?? false)
  const manual = control?.control_source === 'manual'
  const canHold = connected && motorId !== null && manual && !opActive && !busy
  const canJog = connected && held && manual && !opActive
  const { jogging, startRepeat, stopRepeat } = useJog(motorId ?? -1, livePos, JOG_STEP_DEG, canJog)
  useMotorLive((frames) => {
    const pos = motorId === null ? undefined : frames.motors.positions[String(motorId)]
    livePos.current = pos ?? null
  })
  const toggleHold = async () => {
    if (motorId === null) return
    setBusy(true)
    try {
      await api.motorTorque(motorId, !held)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }
  const title = canJog ? `turn ${JOG_STEP_DEG}° (hold to repeat)` : 'hold the motor to jog'
  return (
    <span className="finger-jog">
      <button
        className={`btn ${held ? 'btn-danger' : 'btn-info'}`}
        disabled={!canHold}
        title={held ? 'release: the motor turns freely' : 'hold: torque on, the motor pins where it is'}
        onClick={() => void toggleHold()}
      >
        {held ? 'release' : 'hold'}
      </button>
      <button
        className="btn btn-secondary"
        disabled={!canJog}
        title={title}
        onPointerDown={() => startRepeat(-1)}
        onPointerUp={stopRepeat}
        onPointerLeave={stopRepeat}
        onPointerCancel={stopRepeat}
      >
        −
      </button>
      <button
        className="btn btn-secondary"
        disabled={!canJog}
        title={title}
        onPointerDown={() => startRepeat(1)}
        onPointerUp={stopRepeat}
        onPointerLeave={stopRepeat}
        onPointerCancel={stopRepeat}
      >
        +
      </button>
      {jogging && <small>jogging…</small>}
    </span>
  )
}

function TendonRow({
  tendon,
  index,
  motors,
  connected,
  locked,
}: {
  tendon: FingerTendon
  index: number
  motors: BenchMotor[]
  connected: boolean
  locked: boolean
}) {
  const patchTendon = useFingerStore((s) => s.patchTendon)
  const removeTendon = useFingerStore((s) => s.removeTendon)
  const tendons = useFingerStore((s) => s.tendons)
  const joints = useFingerStore((s) => s.joints)
  const posRef = useRef<HTMLSpanElement>(null)
  useMotorLive((frames) => {
    const pos = tendon.motor === null ? undefined : frames.motors.positions[String(tendon.motor)]
    if (posRef.current) posRef.current.textContent = formatDeg(pos)
  })
  const used = new Set(tendons.map((t) => t.motor))
  const options = motors.filter((m) => m.id === tendon.motor || !used.has(m.id))
  const movers = joints.filter((j) => j.terms.some((t) => t.tendon === tendon.name)).map((j) => j.name)

  return (
    <div className={`finger-row finger-tendon ${tendon.motor === null ? 'incomplete' : ''}`}>
      <div className="finger-row-main">
        <input
          className="finger-name"
          value={tendon.name}
          disabled={locked}
          title="tendon name, as the coupling will call it"
          onChange={(e) => patchTendon(index, { name: e.target.value })}
        />
        <span className="finger-term-times">on</span>
        <select
          value={tendon.motor ?? ''}
          disabled={locked}
          title="the motor this tendon is wound on"
          onChange={(e) => patchTendon(index, { motor: e.target.value === '' ? null : parseInt(e.target.value, 10) })}
        >
          <option value="">no motor</option>
          {options.map((m) => (
            <option key={m.id} value={m.id}>
              motor {m.number} · id {m.id}
            </option>
          ))}
        </select>
        <span className="finger-live" title="live shaft position">
          <span ref={posRef}>—</span>
        </span>
        <MotorHandles motorId={tendon.motor} connected={connected} />
        <span className="finger-span">{movers.length ? `moves ${movers.join(', ')}` : 'moves nothing yet'}</span>
        <span className="finger-row-tools">
          <button
            className="btn btn-secondary finger-remove"
            disabled={locked}
            title="remove this tendon"
            onClick={() => removeTendon(index)}
          >
            ×
          </button>
        </span>
      </div>
    </div>
  )
}

export function FingerTendons({ connected, locked }: { connected: boolean; locked: boolean }) {
  const tendons = useFingerStore((s) => s.tendons)
  const joints = useFingerStore((s) => s.joints)
  const addTendon = useFingerStore((s) => s.addTendon)
  const addHand = useFingerStore((s) => s.addHand)
  const motors = useBenchStore((s) => s.motors)
  const unwound = tendons.filter((t) => t.motor === null).length

  return (
    <section className="panel finger-setup">
      <div className="panel-header">
        <h2>Tendons</h2>
        <small className="finger-hint">
          name each tendon and pick the motor it is wound on — hold a motor and jog it to see which tendon
          moves
        </small>
        <button
          className="btn btn-secondary"
          disabled={locked}
          title="start from a whole hand: a tendon per phalanx on the motors in number order, its joints, MCP and PIP coupled"
          onClick={() => {
            if ((tendons.length === 0 && joints.length === 0) || window.confirm('Replace the tendons and joints with a full hand?'))
              addHand()
          }}
        >
          full hand
        </button>
        <button className="btn btn-secondary" disabled={locked || tendons.length >= 32} onClick={addTendon}>
          + tendon
        </button>
      </div>
      {tendons.length === 0 ? (
        <p className="panel-empty">
          No tendons yet. Press full hand for the usual set, or add them one by one. {motors.length} motor(s)
          on the bus.
        </p>
      ) : (
        <>
          {tendons.map((tendon, index) => (
            <TendonRow
              key={index}
              tendon={tendon}
              index={index}
              motors={motors}
              connected={connected}
              locked={locked}
            />
          ))}
          <p className="finger-hint">
            {unwound ? `${unwound} tendon(s) without a motor · ` : ''}
            {motors.length - tendons.filter((t) => t.motor !== null).length} motor(s) free
          </p>
        </>
      )}
    </section>
  )
}

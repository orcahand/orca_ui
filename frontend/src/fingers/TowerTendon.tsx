// The tendon a motor picked on the tower winds: choose one of the hand's
// tendons (taking it off whichever motor had it), name a new one onto this
// motor, or free the motor. The same assignment the Tendons step edits.

import { useState } from 'react'
import { useOperationActive } from '../state/operationStore'
import { type BenchMotor, useBenchStore } from '../bench/benchStore'
import { NAME_RE, useFingerStore } from './fingerStore'

export function TowerTendon({ motor }: { motor: BenchMotor }) {
  const tendons = useFingerStore((s) => s.tendons)
  const patchTendon = useFingerStore((s) => s.patchTendon)
  const setTendons = useFingerStore((s) => s.setTendons)
  const motors = useBenchStore((s) => s.motors)
  const locked = useOperationActive()
  const [name, setName] = useState('')
  const index = tendons.findIndex((t) => t.motor === motor.id)

  const pick = (value: string) => {
    if (value === '') {
      if (index >= 0) patchTendon(index, { motor: null })
    } else patchTendon(Number(value), { motor: motor.id })
  }

  const trimmed = name.trim()
  const clash = tendons.some((t) => t.name.toLowerCase() === trimmed.toLowerCase())
  const nameOk = NAME_RE.test(trimmed) && !clash
  const add = () => {
    if (!nameOk) return
    setTendons([
      ...tendons.map((t) => (t.motor === motor.id ? { ...t, motor: null } : t)),
      { name: trimmed, motor: motor.id },
    ])
    setName('')
  }

  const where = (id: number | null) => {
    if (id === null) return 'free'
    if (id === motor.id) return 'this motor'
    const m = motors.find((x) => x.id === id)
    return m ? `on motor ${m.number}` : `on id ${id}`
  }

  return (
    <div className="tower-tendon">
      <div className="tower-actions">
        <label className="tower-note" htmlFor={`tower-tendon-${motor.id}`}>
          tendon
        </label>
        <select
          id={`tower-tendon-${motor.id}`}
          value={index >= 0 ? index : ''}
          disabled={locked}
          title="the tendon wound on this motor — one already on another motor moves here"
          onChange={(e) => pick(e.target.value)}
        >
          <option value="">none</option>
          {tendons.map((t, i) => (
            <option key={i} value={i}>
              {t.name} · {where(t.motor)}
            </option>
          ))}
        </select>
      </div>
      <div className="tower-actions">
        <input
          value={name}
          disabled={locked || tendons.length >= 32}
          placeholder="new tendon…"
          title="name a new tendon onto this motor"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add()
          }}
        />
        <button className="btn btn-secondary" disabled={locked || !nameOk || tendons.length >= 32} onClick={add}>
          Add
        </button>
        {trimmed !== '' && clash && <span className="tower-warn">taken</span>}
      </div>
    </div>
  )
}

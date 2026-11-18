// Testing one finger's coupling on the hand, two ways. Drive: hold the
// motors and drag a joint's slider — every motor turns by its share of the
// inverse, so if the equations fit the finger only that joint moves; the
// sliders are joint degrees from where the motors were held (or "zero here"
// was pressed). Bend: release them, bend one joint closed by hand, and each
// equation is judged on its own — it must read its own bend, positive, and
// not the others'. A wrong one gets the sign fix that makes it fit, and
// when one tendon's sign is off in every equation (it is wound the other way
// round its spool) one button flips it in all of them. The
// equations themselves, and their confirm boxes, are the lines above.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'
import { useOperationActive } from '../state/operationStore'
import { useBenchStore } from '../bench/benchStore'
import { useMotorLive } from '../bench/useMotorLive'
import { type Coupling, couplingProblem, couplingsOf, shaftDeltaFor } from './coupling'
import { resolve, useFingerStore } from './fingerStore'

// Slider span either side of the held pose, in joint degrees.
const SLIDER_DEG = 60
// How often the latest slider position goes to the motors.
const SEND_MS = 60
// Shaft degrees per write: caps the speed at about 100°/s, a far jump is walked.
const MAX_SHAFT_STEP_DEG = 6
const DEG = Math.PI / 180

// Shaft degrees a bend must reach before it counts, and joint degrees an
// equation must read of its own bend.
const BEND_MIN_DEG = 8
const READ_MIN_DEG = 4
// An equation reading more than this share of another joint's bend is crosstalk.
const CROSS_OK = 0.3

const signed = (v: number, digits = 1) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}`

// What an equation row (coefficients per motor) reads of each recorded bend.
const readOf = (row: number[], dθ: number[]) => row.reduce((sum, g, i) => sum + g * dθ[i], 0)

/** Whether a row reads its own bend (positive, big enough) and not the others. */
function fits(row: number[], own: number, peaks: Record<number, number[]>): boolean {
  const mine = peaks[own]
  if (!mine) return false
  const q = readOf(row, mine)
  if (q < READ_MIN_DEG) return false
  return Object.entries(peaks).every(([k, p]) => Number(k) === own || Math.abs(readOf(row, p)) <= CROSS_OK * q)
}

/** The fewest sign flips (columns of the row) that make it fit, or null. */
function signFix(row: number[], own: number, peaks: Record<number, number[]>): number[] | null {
  const cols = row.map((g, i) => (g !== 0 ? i : -1)).filter((i) => i >= 0)
  let best: number[] | null = null
  for (let mask = 1; mask < 1 << cols.length; mask++) {
    const flip = cols.filter((_, b) => mask & (1 << b))
    if (best && flip.length >= best.length) continue
    if (fits(row.map((g, i) => (flip.includes(i) ? -g : g)), own, peaks)) best = flip
  }
  return best
}

function CouplingCard({ coupling, connected, locked }: { coupling: Coupling; connected: boolean; locked: boolean }) {
  const tendons = useFingerStore((s) => s.tendons)
  const joints = useFingerStore((s) => s.joints)
  const flipTerms = useFingerStore((s) => s.flipTerms)
  const motors = useBenchStore((s) => s.motors)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const [busy, setBusy] = useState(false)
  const [targets, setTargets] = useState<number[]>(() => coupling.joints.map(() => 0))
  const positions = useRef<Record<string, number>>({})
  const base = useRef<Record<string, number> | null>(null)
  const sent = useRef<Record<string, number>>({})
  const sending = useRef(false)
  const targetsRef = useRef(targets)
  targetsRef.current = targets
  const readRefs = useRef<(HTMLElement | null)[]>([])
  // Bend test: which joint is being bent, from where, and the furthest each
  // recorded bend got (shaft degrees per motor of the coupling).
  const [testing, setTesting] = useState<number | null>(null)
  const [peaks, setPeaks] = useState<Record<number, number[]>>({})
  const testBase = useRef<Record<string, number> | null>(null)
  const bendRef = useRef<HTMLElement>(null)

  const stored = coupling.joints.map((cj) => joints.findIndex((j) => j.name === cj.name))
  const held = new Set(control?.held_motors ?? [])
  const allHeld = coupling.motors.every((m) => held.has(m))
  const manual = control?.control_source === 'manual'
  const canHold = connected && manual && !opActive && !busy
  const canDrive = connected && manual && !opActive && allHeld && coupling.solvable

  const tendonOn = (motor: number) => {
    const index = tendons.findIndex((t) => t.motor === motor)
    return { index, tendon: index >= 0 ? tendons[index] : undefined }
  }
  const motorName = (id: number) => `motor ${motors.find((m) => m.id === id)?.number ?? id}`

  // Zero the sliders at the shafts' present positions.
  const zeroHere = () => {
    base.current = { ...positions.current }
    sent.current = {}
    setTargets(coupling.joints.map(() => 0))
  }

  // A new equation means new slider meanings: start from here.
  const equationKey = JSON.stringify([coupling.motors, coupling.matrix])
  useEffect(() => {
    zeroHere()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equationKey])

  useMotorLive((frames) => {
    positions.current = frames.motors.positions
    if (base.current === null || Object.keys(base.current).length === 0) base.current = { ...positions.current }
    const b = base.current
    const dθ = coupling.motors.map((m) => (positions.current[String(m)] ?? NaN) - (b[String(m)] ?? NaN))
    coupling.matrix.forEach((row, j) => {
      const q = row.reduce((sum, g, i) => sum + g * dθ[i], 0)
      const el = readRefs.current[j]
      if (el) el.textContent = Number.isNaN(q) ? '—' : `${signed(q)}°`
    })
    if (testing === null) return
    if (testBase.current === null) testBase.current = { ...positions.current }
    const t = testBase.current
    const bend = coupling.motors.map((m) => (positions.current[String(m)] ?? NaN) - (t[String(m)] ?? NaN))
    if (bend.some(Number.isNaN)) return
    if (bendRef.current) {
      bendRef.current.textContent = coupling.joints
        .map((j, r) => `${j.name} ${signed(readOf(coupling.matrix[r], bend))}°`)
        .join(' · ')
    }
    const size = Math.max(...bend.map(Math.abs))
    const prev = peaks[testing]
    if (size >= BEND_MIN_DEG && (!prev || size > Math.max(...prev.map(Math.abs)) + 0.5))
      setPeaks((p) => ({ ...p, [testing]: bend }))
  })

  const startBend = (j: number) => {
    testBase.current = null
    if (testing === j) {
      setTesting(null)
      return
    }
    setPeaks((p) => {
      const next = { ...p }
      delete next[j]
      return next
    })
    setTesting(j)
  }

  // Shaft targets for the sliders: the held pose plus the inverse times q.
  const shaftTargets = (): Record<number, number> | null => {
    const b = base.current
    if (!b) return null
    const out: Record<number, number> = {}
    for (const m of coupling.motors) {
      const start = b[String(m)]
      if (start === undefined) return null
      out[m] = start
    }
    for (const [j, joint] of coupling.joints.entries()) {
      const q = targetsRef.current[j]
      if (q === 0) continue
      const deltas = shaftDeltaFor(coupling, joint.name, q)
      if (!deltas) return null
      for (const m of coupling.motors) out[m] += deltas[m]
    }
    return out
  }

  useEffect(() => {
    if (!canDrive) return
    const timer = window.setInterval(async () => {
      if (sending.current) return
      const want = shaftTargets()
      if (!want) return
      const moves = coupling.motors.filter((m) => Math.abs(want[m] - (sent.current[m] ?? NaN)) > 0.05 || sent.current[m] === undefined)
      if (moves.length === 0) return
      sending.current = true
      try {
        if (!useAppStore.getState().control?.direct_motor_mode) await api.motorsDirectMode(true)
        for (const m of moves) {
          const live = positions.current[String(m)]
          if (live === undefined) continue
          const step = Math.max(-MAX_SHAFT_STEP_DEG, Math.min(MAX_SHAFT_STEP_DEG, want[m] - live))
          const target = live + step
          await api.motorsDirectPosition(m, target * DEG)
          // Only call it reached when the whole way was sent; else walk on next tick.
          if (target === want[m]) sent.current[m] = target
          else delete sent.current[m]
        }
        setError(null)
      } catch (error) {
        setError(String((error as Error).message ?? error))
      } finally {
        sending.current = false
      }
    }, SEND_MS)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canDrive, equationKey])

  const toggleHold = async () => {
    setBusy(true)
    try {
      // Holding pins the finger where it is: the sliders start from there.
      if (!allHeld) zeroHere()
      for (const id of coupling.motors) if (held.has(id) !== !allHeld) await api.motorTorque(id, !allHeld)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  // Per equation: does it fit the bends recorded, and if not, which of its
  // terms to flip. Then one tendon whose sign, flipped in every equation,
  // fixes them all.
  const allRecorded = coupling.joints.every((_, r) => peaks[r])
  const verdicts = coupling.joints.map((joint, r) => {
    const row = coupling.matrix[r]
    const own = peaks[r]
    const reads = Object.entries(peaks).map(([k, p]) => ({ k: Number(k), q: readOf(row, p) }))
    const text = reads.map(({ k, q }) => `${coupling.joints[k].name} bend ${signed(q)}°`).join(', ')
    if (!own) return { ok: false, text: `bend ${joint.name} to check it`, flip: null as number[] | null }
    if (fits(row, r, peaks))
      return {
        ok: true,
        text: `✓ reads ${text}${allRecorded ? '' : ' — bend the other joints too, to rule out crosstalk'}`,
        flip: null,
      }
    const flip = signFix(row, r, peaks)
    return { ok: false, text: `✗ reads ${text}`, flip }
  })
  const anyConfirmed = stored.some((i) => joints[i]?.confirmed)
  const tendonFix =
    allRecorded && !anyConfirmed && !verdicts.every((v) => v.ok)
      ? coupling.motors.findIndex((_, c) =>
          coupling.matrix.every((row, r) => fits(row.map((g, i) => (i === c ? -g : g)), r, peaks)),
        )
      : -1
  // A column of the coupling, as the stored joint's term index.
  const termOf = (r: number, c: number) => {
    const joint = joints[stored[r]]
    const tendon = tendonOn(coupling.motors[c]).tendon
    return joint ? joint.terms.findIndex((t) => t.tendon === tendon?.name) : -1
  }
  // The equation as its line will read after the flip, in the line's own order.
  const preview = (r: number, flip: number[]) => {
    const flipped = new Set(flip.map((c) => termOf(r, c)))
    return (joints[stored[r]]?.terms ?? [])
      .map((t, k) => {
        const g = flipped.has(k) ? -t.gain : t.gain
        return `${g < 0 ? '−' : k ? '+' : ''}${Math.abs(g).toFixed(2)}·θ(${t.tendon ?? '?'})`
      })
      .join(' ')
  }

  const names = coupling.motors.map(motorName).join(', ')
  const anyHeldNow = coupling.motors.some((m) => held.has(m))
  return (
    <div className="coupling-check">
      <div className="coupling-check-head">
        <b>check</b>
        {coupling.motors.map((m) => {
          const { index, tendon } = tendonOn(m)
          return (
            <span key={m} className="coupling-check-tendon">
              {tendon?.name ?? '?'} <small>{motorName(m)}</small>
              {index < 0 && <small>no tendon</small>}
            </span>
          )
        })}
        <button
          className={`btn ${allHeld ? 'btn-danger' : 'btn-info'}`}
          disabled={!canHold}
          title={allHeld ? `release ${names}: the motors turn freely` : `hold ${names}: the sliders start from this pose`}
          onClick={() => void toggleHold()}
        >
          {allHeld ? 'release' : 'hold'}
        </button>
        <button className="btn btn-secondary" title="sliders back to 0 at the present pose" onClick={zeroHere}>
          zero here
        </button>
      </div>
      {coupling.joints.map((joint, j) => (
        <div key={joint.name} className="coupling-check-slider">
          <span>{joint.name}</span>
          <input
            type="range"
            min={-SLIDER_DEG}
            max={SLIDER_DEG}
            step={0.5}
            value={targets[j]}
            disabled={!canDrive}
            title={canDrive ? `${joint.name} in joint degrees; the other joints should stay put` : `hold ${names} to drive`}
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              setTargets((t) => t.map((x, k) => (k === j ? v : x)))
            }}
            onDoubleClick={() => setTargets((t) => t.map((x, k) => (k === j ? 0 : x)))}
          />
          <span className="num" title="slider target">
            {signed(targets[j])}°
          </span>
          <span className="num coupling-check-read" title="what the equation reads off the shafts">
            reads{' '}
            <b
              ref={(el) => {
                readRefs.current[j] = el
              }}
            >
              —
            </b>
          </span>
        </div>
      ))}
      {!coupling.solvable && (
        <p className="tower-warn">
          These equations are not independent (one is a multiple of the other), so the sliders cannot drive
          them — bend each joint by hand to see which equation to fix.
        </p>
      )}
      <div className="coupling-check-bend">
        <span title="release the motors, press a joint, bend only that joint closed by hand">bend by hand:</span>
        {coupling.joints.map((joint, j) => (
          <button
            key={joint.name}
            className={`btn ${testing === j ? 'btn-primary' : peaks[j] ? 'btn-info' : 'btn-secondary'}`}
            title={`bend only ${joint.name} closed by hand, then stop; press again to record it afresh`}
            onClick={() => startBend(j)}
          >
            {testing === j ? `bending ${joint.name}… stop` : `${peaks[j] ? '✓ ' : ''}${joint.name}`}
          </button>
        ))}
        {testing !== null && (
          <small className="num">
            <b ref={bendRef}>bend it</b>
            {anyHeldNow && ' · a motor is held: release it to bend'}
          </small>
        )}
      </div>
      {Object.keys(peaks).length > 0 && (
        <ul className="coupling-check-verdicts">
          {coupling.joints.map((joint, r) => {
            const v = verdicts[r]
            const confirmed = joints[stored[r]]?.confirmed ?? false
            const terms = v.flip?.map((c) => termOf(r, c)).filter((t) => t >= 0) ?? []
            return (
              <li key={joint.name} className={v.ok ? 'ok' : peaks[r] ? 'bad' : ''}>
                <b>{joint.name}</b> {v.text}
                {v.flip && terms.length > 0 && (
                  <button
                    className="btn btn-info"
                    disabled={locked || confirmed}
                    title={confirmed ? 'confirmed: unconfirm it to change it' : 'flip the signs that make this equation fit the bends'}
                    onClick={() => flipTerms(stored[r], terms)}
                  >
                    make it {preview(r, v.flip)}
                  </button>
                )}
                {!v.ok && peaks[r] && !v.flip && allRecorded && <small> — no sign fits: check the tendons and the radii</small>}
                {confirmed && <small> · confirmed</small>}
              </li>
            )
          })}
          {tendonFix >= 0 && (
            <li className="bad">
              {tendonOn(coupling.motors[tendonFix]).tendon?.name} has the wrong sign in every equation (it is wound
              the other way round its spool).
              <button
                className="btn btn-info"
                disabled={locked}
                onClick={() => stored.forEach((i, r) => flipTerms(i, [termOf(r, tendonFix)].filter((t) => t >= 0)))}
              >
                flip θ({tendonOn(coupling.motors[tendonFix]).tendon?.name}) in all {coupling.joints.length} lines
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

/** The quick test for every multi-joint coupling of one finger. */
export function CouplingCheck({ group, connected, locked }: { group: string; connected: boolean; locked: boolean }) {
  const joints = useFingerStore((s) => s.joints)
  const tendons = useFingerStore((s) => s.tendons)
  const couplings = useMemo(
    () =>
      couplingsOf(resolve(joints, tendons)).filter(
        // A singular one stays: the bend test shows which equation is off.
        (c) =>
          c.joints.length > 1 &&
          c.joints.every((j) => j.group === group) &&
          (couplingProblem(c) === null || (c.motors.length === c.joints.length && !c.solvable)),
      ),
    [joints, tendons, group],
  )
  return (
    <>
      {couplings.map((c) => (
        <CouplingCard key={c.joints.map((j) => j.name).join('+')} coupling={c} connected={connected} locked={locked} />
      ))}
    </>
  )
}

// Beside the fingers workflow: one current trace for every motor on the
// bus, named by the tendon wound on it, and a dial per wrist axis showing
// the live joint angle through the coupling with its captured ends.

import { useMemo, useRef } from 'react'
import { MotorStripChart, seriesColors } from '../bench/BenchChart'
import { useBenchStore } from '../bench/benchStore'
import { formatDeg, useMotorLive } from '../bench/useMotorLive'
import { usePalette } from '../theme/themeStore'
import { type MotorJoint, couplingProblem, couplingsOf, jointAnglesOf } from './coupling'
import { fractionOf, resolve, useFingerStore } from './fingerStore'

const DIAL_R = 34

function WristDial({ joint, all }: { joint: MotorJoint; all: MotorJoint[] }) {
  const zeros = useFingerStore((s) => s.zeros)
  const coupling = useMemo(() => couplingsOf(all).find((c) => c.joints.some((j) => j.name === joint.name)), [all, joint.name])
  const problem = coupling ? couplingProblem(coupling) : 'no tendon'
  const needle = useRef<SVGLineElement>(null)
  const text = useRef<SVGTextElement>(null)
  const pct = useRef<HTMLElement>(null)
  // Ends at ±120° on the dial when both are captured, else the angle itself.
  const lo = joint.open_deg
  const hi = joint.closed_deg
  const ends = lo !== null && hi !== null && Math.abs(hi - lo) >= 1
  const sweep = (angle: number): number =>
    ends ? -120 + 240 * (fractionOf(joint, angle) ?? 0) : Math.max(-150, Math.min(150, angle))
  useMotorLive((frames) => {
    const angle = coupling && !problem ? jointAnglesOf([coupling], zeros, frames.motors.positions)[joint.name] : undefined
    if (needle.current) needle.current.setAttribute('transform', `rotate(${angle === undefined ? 0 : sweep(angle)})`)
    if (text.current) text.current.textContent = formatDeg(angle, 0)
    if (pct.current) {
      const f = angle === undefined || !ends ? null : fractionOf(joint, angle)
      pct.current.textContent = f === null || f === undefined ? '' : `${Math.round(f * 100)}%`
    }
  })
  const mark = (deg: number, label: string) => {
    const a = ((deg - 90) * Math.PI) / 180
    return (
      <text key={label} x={Math.cos(a) * (DIAL_R + 10)} y={Math.sin(a) * (DIAL_R + 10) + 3} textAnchor="middle">
        {label}
      </text>
    )
  }
  return (
    <div className={`wrist-dial ${problem ? 'incomplete' : ''}`} title={problem ?? `${joint.name}, open ${lo}° → closed ${hi}°`}>
      <svg viewBox="-56 -56 112 112" width={112} height={112}>
        <circle r={DIAL_R} />
        {ends ? [mark(-120, 'open'), mark(120, 'closed')] : [mark(0, '0°')]}
        <line ref={needle} x1={0} y1={0} x2={0} y2={-DIAL_R + 4} />
        <circle className="hub" r={3} />
        <text ref={text} y={DIAL_R - 6} textAnchor="middle" className="reading">
          —
        </text>
      </svg>
      <span className="wrist-dial-name">
        {joint.name} <small ref={pct} />
      </span>
    </div>
  )
}

export function FingerMonitor() {
  const motors = useBenchStore((s) => s.motors)
  const tendons = useFingerStore((s) => s.tendons)
  const joints = useFingerStore((s) => s.joints)
  const palette = usePalette()
  const ids = useMemo(() => motors.map((m) => String(m.id)), [motors])
  const colors = seriesColors(palette, ids.length)
  const resolved = useMemo(() => resolve(joints, tendons), [joints, tendons])
  const wrist = resolved.filter((j) => /^wrist/i.test(j.name) || /^wrist$/i.test(j.group))

  return (
    <section className="panel finger-monitor">
      <div className="panel-header">
        <h2>Monitor</h2>
        <small className="finger-hint">current of every motor, last 30 s · wrist angles through the coupling</small>
      </div>
      {ids.length === 0 ? (
        <p className="panel-empty">No motors on the bus.</p>
      ) : (
        <div className="bench-charts">
          <div className="bench-chart-legend finger-chart-legend">
            {motors.map((motor, i) => {
              const tendon = tendons.find((t) => t.motor === motor.id)
              return (
                <span key={motor.id} style={{ color: colors[i] }} title={`motor ${motor.number} · id ${motor.id}`}>
                  ● {tendon ? tendon.name : `motor ${motor.number}`}
                </span>
              )
            })}
          </div>
          <div className="bench-chart-title">current</div>
          <MotorStripChart source="currents" ids={ids} unit="mA" height={160} />
        </div>
      )}
      <div className="bench-chart-title">wrist</div>
      {wrist.length === 0 ? (
        <p className="panel-empty">No wrist joints — name them wrist_… in the Coupling step.</p>
      ) : (
        <div className="wrist-dials">
          {wrist.map((joint) => (
            <WristDial key={joint.name} joint={joint} all={resolved} />
          ))}
        </div>
      )}
    </section>
  )
}

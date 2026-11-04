// Step 4 — control: Engage starts the run, then every joint has a slider
// from open to closed and every finger a curl slider that moves its flexion
// joints together. Everything the operation validates is gated here too, so
// Engage says why it is off instead of bouncing a 409.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/rest'
import type { FingerExtra } from '../api/types'
import { useBenchStore } from '../bench/benchStore'
import { useMotorLive } from '../bench/useMotorLive'
import { useAppStore } from '../state/appStore'
import { isOperationActive, operationLabel, useOperationStore } from '../state/operationStore'
import { type MotorJoint, couplingsOf, jointAnglesOf } from './coupling'
import { fractionOf, groupsOf, readyJoints, resolve, useFingerStore } from './fingerStore'

function JointSlider({ joint, all, engaged }: { joint: MotorJoint; all: MotorJoint[]; engaged: boolean }) {
  const target = useFingerStore((s) => s.targets[joint.name] ?? 0)
  const setTarget = useFingerStore((s) => s.setTarget)
  const zeros = useFingerStore((s) => s.zeros)
  const coupling = useMemo(
    () => couplingsOf(all).find((c) => c.joints.some((j) => j.name === joint.name)),
    [all, joint.name],
  )
  const liveRef = useRef<HTMLElement>(null)
  const markRef = useRef<HTMLElement>(null)

  useMotorLive((frames) => {
    const angle = coupling ? jointAnglesOf([coupling], zeros, frames.motors.positions)[joint.name] : undefined
    const f = angle === undefined ? null : fractionOf(joint, angle)
    if (liveRef.current) liveRef.current.textContent = f === null ? '—' : `${Math.round(f * 100)}%`
    if (markRef.current) markRef.current.style.left = f === null ? '-9999px' : `${(f * 100).toFixed(1)}%`
  })

  return (
    <label
      className="finger-slider"
      title={`${joint.name} = ${joint.terms.map((t) => `${t.gain} · θ(motor ${t.motor})`).join(' + ')}`}
    >
      <span className="finger-slider-name">{joint.name}</span>
      <span className="finger-slider-track">
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(target * 1000)}
          disabled={!engaged}
          onChange={(e) => setTarget(joint.name, parseInt(e.target.value, 10) / 1000)}
        />
        <i ref={markRef} className="finger-slider-live" title="where the joint is" />
      </span>
      <span className="finger-slider-value">
        {Math.round(target * 100)}%
        <small ref={liveRef}>—</small>
      </span>
    </label>
  )
}

function GroupSlider({
  group,
  joints,
  all,
  engaged,
}: {
  group: string
  joints: MotorJoint[]
  all: MotorJoint[]
  engaged: boolean
}) {
  const targets = useFingerStore((s) => s.targets)
  const setTargets = useFingerStore((s) => s.setTargets)
  // The finger's curl moves its flexion joints; abduction is its own axis.
  const flexion = joints.filter((j) => !/_abd$/i.test(j.name))
  const names = (flexion.length ? flexion : joints).map((j) => j.name)
  const values = names.map((n) => targets[n] ?? 0)
  const mean = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0
  const spread = Math.max(...values) - Math.min(...values) > 0.01
  const curl = (fraction: number) => setTargets(Object.fromEntries(names.map((n) => [n, fraction])))

  return (
    <div className="finger-group-block">
      <div className="finger-group-head">
        <h3>{group || 'ungrouped'}</h3>
        {names.length > 1 && (
          <label className="finger-slider master" title="curl this finger: its flexion joints together, abduction untouched">
            <span className="finger-slider-name">curl</span>
            <span className="finger-slider-track">
              <input
                type="range"
                min={0}
                max={1000}
                value={Math.round(mean * 1000)}
                disabled={!engaged}
                onChange={(e) => curl(parseInt(e.target.value, 10) / 1000)}
              />
            </span>
            <span className="finger-slider-value">
              {spread ? '≈' : ''}
              {Math.round(mean * 100)}%
            </span>
          </label>
        )}
        <span className="finger-group-buttons">
          <button className="btn btn-secondary" disabled={!engaged} onClick={() => curl(0)}>
            open
          </button>
          <button className="btn btn-secondary" disabled={!engaged} onClick={() => curl(1)}>
            close
          </button>
        </span>
      </div>
      {joints.map((joint) => (
        <JointSlider key={joint.name} joint={joint} all={all} engaged={engaged} />
      ))}
    </div>
  )
}

export function FingerControl({ connected }: { connected: boolean }) {
  const joints = useFingerStore((s) => s.joints)
  const tendons = useFingerStore((s) => s.tendons)
  const zeros = useFingerStore((s) => s.zeros)
  const settings = useFingerStore((s) => s.settings)
  const patchSettings = useFingerStore((s) => s.patchSettings)
  const seedTargets = useFingerStore((s) => s.seedTargets)
  const setTargets = useFingerStore((s) => s.setTargets)
  const motors = useBenchStore((s) => s.motors)
  const control = useAppStore((s) => s.control)
  const setError = useAppStore((s) => s.setError)
  const operation = useOperationStore((s) => s.operation)
  const [busy, setBusy] = useState(false)

  const active = isOperationActive(operation)
  const ours = active && operation?.kind === 'finger_control'
  const extra = ours ? (operation?.extra as FingerExtra | null) : null
  const resolved = useMemo(() => resolve(joints, tendons), [joints, tendons])
  const ready = useMemo(() => readyJoints(resolved), [resolved])
  const held = control?.held_motors ?? []
  // While engaged the run's joints are the sliders, whatever the file says now.
  const shown = useMemo<MotorJoint[]>(
    () =>
      ours && extra
        ? extra.joints.map((j) => {
            const stored = resolved.find((s) => s.name === j.name)
            return {
              name: j.name,
              group: stored?.group ?? '',
              terms: stored?.terms ?? j.motors.map((motor) => ({ motor, gain: 1 })),
              unresolved: [],
              open_deg: j.open_deg,
              closed_deg: j.closed_deg,
            }
          })
        : ready,
    [ours, extra, resolved, ready],
  )
  const groups = useMemo(() => groupsOf(shown), [shown])

  // The run's targets seed the sliders once per run: on engage, and when the
  // page opens mid-run. After that the sliders lead and the run follows.
  const seededRun = useRef<string | null>(null)
  useEffect(() => {
    if (!ours || !extra || !operation) return
    if (seededRun.current === operation.run_id) return
    if (!extra.joints.length) return
    seededRun.current = operation.run_id
    seedTargets(Object.fromEntries(extra.joints.map((j) => [j.name, j.target])))
  }, [ours, extra, operation, seedTargets])

  let blocked: string | null = null
  if (!connected) blocked = 'no motor bus'
  else if (active) blocked = `${operationLabel(operation!.kind)} is running`
  else if (control && control.control_source !== 'manual')
    blocked = `control is owned by ${control.control_owner}`
  else if (ready.length === 0) blocked = 'no joint is complete — tendons, coupling and both ends'
  else {
    const loose = [...new Set(ready.flatMap((j) => j.terms.map((t) => t.motor)))].filter((m) => !held.includes(m))
    if (loose.length > 0) {
      const names = loose.map((id) => motors.find((m) => m.id === id)?.number ?? id)
      blocked = loose.length > 3 ? 'hold all the motors first' : `hold motor ${names.join(', ')} first`
    }
  }
  const skipped = joints.length - ready.length

  const call = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const engage = () =>
    call(() =>
      api.operationStart('finger_control', {
        joints: ready.map((j) => ({
          name: j.name,
          group: j.group,
          open_deg: j.open_deg,
          closed_deg: j.closed_deg,
          terms: j.terms,
        })),
        zeros,
        speed_deg_s: settings.speedDegS,
      }),
    )
  const disengage = () => call(() => api.operationStop())
  const allNames = groups.flatMap((g) => g.joints.map((j) => j.name))
  const setAll = (fraction: number) => setTargets(Object.fromEntries(allNames.map((n) => [n, fraction])))

  const speed = (text: string) => {
    const value = parseFloat(text)
    if (!Number.isFinite(value) || value < 1 || value > 2000) return
    patchSettings({ speedDegS: value })
    if (ours) api.fingerTargets({}, value).catch(() => undefined)
  }

  return (
    <section className="panel finger-control">
      <div className="panel-header">
        <h2>Control</h2>
        <label className="stress-field" title="joint speed the sliders are followed at">
          speed
          <input type="number" min={1} max={2000} step={10} value={settings.speedDegS} onChange={(e) => speed(e.target.value)} />
          °/s
        </label>
      </div>
      <div className="bench-run-buttons">
        {ours ? (
          <button className="btn btn-danger" disabled={busy} onClick={disengage}>
            ◼ Disengage
          </button>
        ) : (
          <button
            className="btn btn-primary"
            disabled={busy || blocked !== null}
            title={blocked ?? 'take the joints: the sliders go live'}
            onClick={engage}
          >
            ▶ Engage
          </button>
        )}
        <button className="btn btn-secondary" disabled={!ours} onClick={() => setAll(0)}>
          open all
        </button>
        <button className="btn btn-secondary" disabled={!ours} onClick={() => setAll(1)}>
          close all
        </button>
        <span className="bench-run-hint">
          {ours
            ? `${extra?.joints.length ?? 0} joint(s) engaged — the motors stay held when you disengage`
            : blocked ?? `${ready.length} joint(s) ready${skipped ? `, ${skipped} not yet` : ''}`}
        </span>
      </div>
      {groups.length === 0 ? (
        <p className="panel-empty">The sliders appear once a joint has its tendons, a solvable coupling and both ends.</p>
      ) : (
        groups.map((g) => (
          <GroupSlider key={g.group || '\u0000'} group={g.group} joints={g.joints} all={shown} engaged={!!ours} />
        ))
      )}
    </section>
  )
}

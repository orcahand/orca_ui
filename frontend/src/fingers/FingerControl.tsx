// Step 4 — control: Engage starts the run, then every joint has a slider
// from open to closed and every finger a curl slider that moves its flexion
// joints together. The sliders can be kept as named poses, and the run can
// cycle through the poses in order. Everything the operation validates is
// gated here too, so Engage says why it is off instead of bouncing a 409.
// A joint whose ends are not captured yet is driven inside a window of ±
// a few joint degrees around where it is at Engage.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/rest'
import type { FingerExtra, HwErrorInfo } from '../api/types'
import { useBenchStore } from '../bench/benchStore'
import { useMotorLive } from '../bench/useMotorLive'
import { useAppStore } from '../state/appStore'
import { isOperationActive, operationLabel, useOperationStore } from '../state/operationStore'
import { type MotorJoint, couplingsOf, jointAnglesOf } from './coupling'
import {
  type FingerPose,
  WINDOW_DEG,
  drivableJoints,
  fractionOf,
  groupsOf,
  hasRange,
  resolve,
  useFingerStore,
  windowed,
} from './fingerStore'

// Leave joints out of the pose cycle, or let them back in; an engaged run
// hears of it at once, so a running cycle lets go of them or picks them up.
function useCycleSkip(): [Set<string>, (names: string[], skipped: boolean) => void] {
  const skipJoints = useFingerStore((s) => s.settings.cycleSkipJoints)
  const patchSettings = useFingerStore((s) => s.patchSettings)
  const engaged = useOperationStore((s) => isOperationActive(s.operation) && s.operation?.kind === 'finger_control')
  const setError = useAppStore((s) => s.setError)
  const skip = useMemo(() => new Set(skipJoints), [skipJoints])
  const toggle = (names: string[], skipped: boolean) => {
    const next = skipped ? [...new Set([...skipJoints, ...names])] : skipJoints.filter((n) => !names.includes(n))
    patchSettings({ cycleSkipJoints: next })
    if (engaged) api.fingerCycleSkip(next).catch((error) => setError(String((error as Error).message ?? error)))
  }
  return [skip, toggle]
}

function JointSlider({
  joint,
  all,
  engaged,
  short,
  window,
}: {
  joint: MotorJoint
  all: MotorJoint[]
  engaged: boolean
  short: Record<string, number>
  // Half-width of the window the joint is driven in, when it has no captured range.
  window: number | null
}) {
  const motors = useBenchStore((s) => s.motors)
  const shortText = Object.entries(short)
    .map(([id, deg]) => `motor ${motors.find((m) => m.id === Number(id))?.number ?? id} ${deg > 0 ? '+' : ''}${deg.toFixed(0)}°`)
    .join(', ')
  const target = useFingerStore((s) => s.targets[joint.name] ?? 0)
  const setTarget = useFingerStore((s) => s.setTarget)
  const zeros = useFingerStore((s) => s.zeros)
  const coupling = useMemo(
    () => couplingsOf(all).find((c) => c.joints.some((j) => j.name === joint.name)),
    [all, joint.name],
  )
  const liveRef = useRef<HTMLElement>(null)
  const markRef = useRef<HTMLElement>(null)
  const loadRef = useRef<HTMLElement>(null)
  const maxCurrent = useAppStore((s) => s.control?.max_current ?? null)
  const [skip, toggleSkip] = useCycleSkip()
  const skipped = skip.has(joint.name)

  useMotorLive((frames) => {
    const angle = coupling ? jointAnglesOf([coupling], zeros, frames.motors.positions)[joint.name] : undefined
    const f = angle === undefined ? null : fractionOf(joint, angle)
    if (liveRef.current) liveRef.current.textContent = f === null ? '—' : `${Math.round(f * 100)}%`
    if (markRef.current) markRef.current.style.left = f === null ? '-9999px' : `${(f * 100).toFixed(1)}%`
    // A motor sitting at the ceiling cannot pull further: the joint stops short.
    const currents = joint.terms.map((t) => Math.abs(frames.motors.currents[String(t.motor)] ?? 0))
    const peak = Math.max(0, ...currents)
    const pinned = maxCurrent !== null && peak >= 0.9 * maxCurrent
    if (loadRef.current) {
      loadRef.current.textContent = pinned ? `${Math.round(peak)} mA at limit` : `${Math.round(peak)} mA`
      loadRef.current.classList.toggle('pinned', pinned)
    }
  })

  return (
    <div
      className={`finger-slider ${skipped ? 'off-cycle' : ''}`}
      title={`${joint.name} = ${joint.terms.map((t) => `${t.gain} · θ(motor ${t.motor})`).join(' + ')}`}
    >
      <span className="finger-slider-name">
        <input
          type="checkbox"
          checked={!skipped}
          title={
            skipped
              ? 'left out of the pose cycle: it holds, and its slider does not end the cycle — tick to cycle it again'
              : 'part of the pose cycle — untick to keep it where it is while the cycle runs'
          }
          onChange={(e) => toggleSkip([joint.name], !e.target.checked)}
        />
        {joint.name}
        {window !== null && (
          <small
            className="finger-slider-window"
            title="no range captured: driven this far either way from where the joint was at Engage (50%)"
          >
            ±{window}°
          </small>
        )}
      </span>
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
      <small ref={loadRef} className="finger-slider-load" title="highest motor current of this joint; at the ceiling the motor stalls">
        —
      </small>
      {shortText && (
        <small className="finger-slider-short" title="the command has settled but these shafts are not at their goal (goal − shaft)">
          short: {shortText}
        </small>
      )}
    </div>
  )
}

function GroupSlider({
  group,
  joints,
  all,
  engaged,
  shorts,
  windows,
}: {
  group: string
  joints: MotorJoint[]
  all: MotorJoint[]
  engaged: boolean
  shorts: Record<string, Record<string, number>>
  windows: Record<string, number>
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
  const [skip, toggleSkip] = useCycleSkip()
  const jointNames = joints.map((j) => j.name)
  const cycledCount = jointNames.filter((n) => !skip.has(n)).length

  return (
    <div className="finger-group-block">
      <div className="finger-group-head">
        <h3>
          <input
            type="checkbox"
            checked={cycledCount > 0}
            ref={(el) => {
              if (el) el.indeterminate = cycledCount > 0 && cycledCount < jointNames.length
            }}
            title="this finger in the pose cycle — untick to keep all its joints where they are while the cycle runs"
            onChange={(e) => toggleSkip(jointNames, !e.target.checked)}
          />
          {group || 'ungrouped'}
        </h3>
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
        <JointSlider
          key={joint.name}
          joint={joint}
          all={all}
          engaged={engaged}
          short={shorts[joint.name] ?? {}}
          window={windows[joint.name] ?? null}
        />
      ))}
    </div>
  )
}

// Named poses of the sliders, and the cycle that walks the run through them.
function PosePanel({ engaged, extra, names }: { engaged: boolean; extra: FingerExtra | null; names: string[] }) {
  const poses = useFingerStore((s) => s.poses)
  const targets = useFingerStore((s) => s.targets)
  const setTargets = useFingerStore((s) => s.setTargets)
  const capturePose = useFingerStore((s) => s.capturePose)
  const removePose = useFingerStore((s) => s.removePose)
  const movePose = useFingerStore((s) => s.movePose)
  const settings = useFingerStore((s) => s.settings)
  const patchSettings = useFingerStore((s) => s.patchSettings)
  const setError = useAppStore((s) => s.setError)
  const [busy, setBusy] = useState(false)
  const cycle = extra?.cycle ?? null

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
  const capture = () => {
    const name = window.prompt('Keep the sliders as pose…', `pose ${poses.length + 1}`)
    if (!name?.trim()) return
    capturePose(name.trim(), Object.fromEntries(names.map((n) => [n, targets[n] ?? 0])))
  }
  // A stored pose may name joints that are not engaged now: only the engaged ones go.
  const goTo = (pose: FingerPose) =>
    setTargets(Object.fromEntries(Object.entries(pose.targets).filter(([n]) => names.includes(n))))
  const skip = new Set(settings.cycleSkip)
  const cycled = poses.filter((p) => !skip.has(p.name))
  const toggleCycled = (name: string) =>
    patchSettings({
      cycleSkip: skip.has(name)
        ? settings.cycleSkip.filter((n) => n !== name)
        : [...settings.cycleSkip.filter((n) => poses.some((p) => p.name === n)), name],
    })
  const startCycle = () =>
    call(() =>
      api.fingerCycle(
        cycled,
        settings.cycleCount,
        settings.cycleDwellS,
        settings.speedDegS,
        settings.cycleSkipJoints.filter((n) => names.includes(n)),
      ),
    )
  const stopCycle = () => call(() => api.fingerCycleStop())
  const describe = (pose: FingerPose) =>
    Object.entries(pose.targets)
      .map(([n, f]) => `${n} ${Math.round(f * 100)}%`)
      .join(' · ')

  return (
    <div className="finger-poses">
      <div className="finger-group-head">
        <h3>poses</h3>
        <button
          className="btn btn-secondary"
          disabled={!engaged || names.length === 0 || poses.length >= 64}
          title="keep where the sliders are now as a named pose"
          onClick={capture}
        >
          + capture pose
        </button>
        <span className="finger-group-buttons">
          {cycle ? (
            <button className="btn btn-danger" disabled={busy} onClick={stopCycle}>
              ◼ stop cycle
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={busy || !engaged || cycled.length < 2}
              title={cycled.length < 2 ? 'a cycle needs at least two ticked poses' : 'walk through the ticked poses in order'}
              onClick={startCycle}
            >
              ▶ cycle {cycled.length < poses.length ? `${cycled.length} of ${poses.length}` : ''}
            </button>
          )}
          <label className="stress-field" title="rounds through the poses; 0 keeps going until stopped">
            ×
            <input
              type="number"
              min={0}
              max={100000}
              step={1}
              value={settings.cycleCount}
              disabled={!!cycle}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10)
                if (Number.isFinite(v) && v >= 0) patchSettings({ cycleCount: v })
              }}
            />
          </label>
          <label className="stress-field" title="how long each pose is held once every joint has arrived">
            dwell
            <input
              type="number"
              min={0}
              max={600}
              step={0.1}
              value={settings.cycleDwellS}
              disabled={!!cycle}
              onChange={(e) => {
                const v = parseFloat(e.target.value)
                if (Number.isFinite(v) && v >= 0) patchSettings({ cycleDwellS: v })
              }}
            />
            s
          </label>
        </span>
        <span className="bench-run-hint">
          {cycle
            ? `${cycle.phase === 'moving' ? 'going to' : 'holding'} ${cycle.pose} (${cycle.index + 1}/${cycle.poses.length}) · round ${cycle.done + 1}${cycle.cycles ? ` of ${cycle.cycles}` : ''}`
            : poses.length
              ? 'go to a pose, or cycle through the ticked ones in this order — moving a ticked joint ends the cycle'
              : 'capture a pose to come back to it'}
        </span>
      </div>
      {poses.map((pose, index) => (
        <div key={pose.name} className={`finger-pose ${cycle?.pose === pose.name ? 'on' : ''}`}>
          <input
            type="checkbox"
            checked={!skip.has(pose.name)}
            disabled={!!cycle}
            title="part of the cycle"
            onChange={() => toggleCycled(pose.name)}
          />
          <button className="btn btn-secondary" disabled={!engaged || !!cycle} title={describe(pose)} onClick={() => goTo(pose)}>
            go
          </button>
          <span className="finger-pose-name">{pose.name}</span>
          <span className="finger-pose-detail" title={describe(pose)}>
            {describe(pose)}
          </span>
          <span className="finger-row-tools">
            <button
              className="btn btn-secondary"
              disabled={!engaged || !!cycle}
              title="overwrite this pose with where the sliders are now"
              onClick={() => capturePose(pose.name, Object.fromEntries(names.map((n) => [n, targets[n] ?? 0])))}
            >
              update
            </button>
            <button className="btn btn-secondary" disabled={!!cycle || index === 0} title="move up" onClick={() => movePose(index, -1)}>
              ↑
            </button>
            <button className="btn btn-secondary" disabled={!!cycle || index === poses.length - 1} title="move down" onClick={() => movePose(index, 1)}>
              ↓
            </button>
            <button className="btn btn-secondary finger-remove" disabled={!!cycle} title="forget this pose" onClick={() => removePose(index)}>
              ×
            </button>
          </span>
        </div>
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
  // Latched hardware errors by motor id, from the fault stream; a latched
  // motor acks torque and never moves, so it must be cleared before Engage.
  const [faults, setFaults] = useState<Record<number, HwErrorInfo>>({})
  const positions = useRef<Record<string, number>>({})
  useMotorLive((frames) => {
    positions.current = frames.motors.positions
    const next: Record<number, HwErrorInfo> = {}
    for (const [id, entry] of Object.entries(frames.motors.faults?.motors ?? {})) {
      if (entry.hw_error) next[Number(id)] = entry.hw_error
    }
    setFaults((prev) => {
      const same =
        Object.keys(prev).length === Object.keys(next).length &&
        Object.entries(next).every(([id, e]) => prev[Number(id)]?.headline === e.headline)
      return same ? prev : next
    })
  })
  const clearFault = (id: number) =>
    call(async () => {
      const r = await api.rebootMotor(id)
      if (!r.cleared) throw new Error(`motor ${motors.find((m) => m.id === id)?.number ?? id} still reports ${r.hw_error_flags?.join(', ')}`)
    })

  const active = isOperationActive(operation)
  const ours = active && operation?.kind === 'finger_control'
  const extra = ours ? (operation?.extra as FingerExtra | null) : null
  const resolved = useMemo(() => resolve(joints, tendons), [joints, tendons])
  const ready = useMemo(() => drivableJoints(resolved), [resolved])
  const unranged = ready.filter((j) => !hasRange(j))
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
  // While engaged, the half-width each unranged joint was engaged with.
  const windows = useMemo<Record<string, number>>(() => {
    const out: Record<string, number> = {}
    for (const j of shown) {
      const stored = resolved.find((s) => s.name === j.name)
      if (stored && !hasRange(stored) && j.open_deg !== null && j.closed_deg !== null)
        out[j.name] = Math.round(Math.abs(j.closed_deg - j.open_deg) / 2)
      else if (stored && !hasRange(stored)) out[j.name] = settings.windowDeg
    }
    return out
  }, [shown, resolved, settings.windowDeg])
  const shorts = useMemo(
    () => Object.fromEntries((extra?.joints ?? []).map((j) => [j.name, j.short ?? {}])),
    [extra],
  )

  // The run's targets seed the sliders once per run: on engage, and when the
  // page opens mid-run. After that the sliders lead and the run follows.
  const seededRun = useRef<string | null>(null)
  useEffect(() => {
    if (!ours || !extra || !operation) return
    if (!extra.joints.length) return
    // While a cycle runs the run leads, and the sliders show where it is going.
    if (seededRun.current === operation.run_id && !extra.cycle) return
    const fresh = seededRun.current !== operation.run_id
    seededRun.current = operation.run_id
    // Joints the cycle leaves alone keep their sliders: the hand leads there.
    const skip = new Set(extra.cycle_skip ?? [])
    const run = extra.joints.filter((j) => fresh || !skip.has(j.name))
    seedTargets({ ...useFingerStore.getState().targets, ...Object.fromEntries(run.map((j) => [j.name, j.target])) })
  }, [ours, extra, operation, seedTargets])

  let blocked: string | null = null
  if (!connected) blocked = 'no motor bus'
  else if (active) blocked = `${operationLabel(operation!.kind)} is running`
  else if (control && control.control_source !== 'manual')
    blocked = `control is owned by ${control.control_owner}`
  else if (ready.length === 0) blocked = 'no joint can be driven — put its tendons on motors, with a solvable coupling'
  else {
    const inPlay = [...new Set(ready.flatMap((j) => j.terms.map((t) => t.motor)))]
    const tripped = inPlay.filter((m) => faults[m])
    const loose = inPlay.filter((m) => !held.includes(m))
    if (tripped.length > 0) {
      const names = tripped.map((id) => motors.find((m) => m.id === id)?.number ?? id)
      blocked = `motor ${names.join(', ')} tripped — clear the fault first`
    } else    if (loose.length > 0) {
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
    call(() => {
      const angles = jointAnglesOf(couplingsOf(ready), zeros, positions.current)
      const blind = unranged.filter((j) => angles[j.name] === undefined).map((j) => j.name)
      if (blind.length) throw new Error(`no shaft reading for ${blind.join(', ')} — cannot place its window`)
      const sent = ready.map((j) => (hasRange(j) ? j : windowed(j, angles[j.name], settings.windowDeg)))
      return api.operationStart('finger_control', {
        joints: sent.map((j) => ({
          name: j.name,
          group: j.group,
          open_deg: j.open_deg,
          closed_deg: j.closed_deg,
          terms: j.terms,
        })),
        zeros,
        speed_deg_s: settings.speedDegS,
      })
    })
  const disengage = () => call(() => api.operationStop())
  const allNames = groups.flatMap((g) => g.joints.map((j) => j.name))
  const setAll = (fraction: number) => setTargets(Object.fromEntries(allNames.map((n) => [n, fraction])))

  const speed = (text: string) => {
    const value = parseFloat(text)
    if (!Number.isFinite(value) || value < 1 || value > 2000) return
    patchSettings({ speedDegS: value })
    if (ours) api.fingerTargets({}, value).catch(() => undefined)
  }
  const windowDeg = (text: string) => {
    const value = parseFloat(text)
    if (Number.isFinite(value) && value >= WINDOW_DEG.min && value <= WINDOW_DEG.max) patchSettings({ windowDeg: value })
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
        <label
          className="stress-field"
          title="a joint without a captured range is driven this many joint degrees either way from where it is at Engage — capture its ends in Range to use the real ones"
        >
          window ±
          <input
            type="number"
            min={WINDOW_DEG.min}
            max={WINDOW_DEG.max}
            step={5}
            value={settings.windowDeg}
            disabled={!!ours}
            onChange={(e) => windowDeg(e.target.value)}
          />
          °
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
            : blocked ??
              `${ready.length} joint(s) ready` +
                (unranged.length ? `, ${unranged.length} on a ±${settings.windowDeg}° window` : '') +
                (skipped ? `, ${skipped} not drivable yet` : '')}
        </span>
      </div>
      {Object.entries(faults).map(([id, fault]) => {
        const motor = motors.find((m) => m.id === Number(id))
        const tendon = tendons.find((t) => t.motor === Number(id))
        return (
          <div key={id} className="finger-fault" title={fault.advice}>
            <strong>
              motor {motor?.number ?? id}
              {tendon ? ` (${tendon.name})` : ''}
            </strong>{' '}
            {fault.headline} — {fault.advice}
            <button className="btn btn-danger" disabled={busy || ours} onClick={() => clearFault(Number(id))}>
              clear
            </button>
          </div>
        )
      })}
      <PosePanel engaged={!!ours} extra={extra} names={shown.map((j) => j.name)} />
      {groups.length === 0 ? (
        <p className="panel-empty">The sliders appear once a joint's tendons are on motors and its coupling can be solved.</p>
      ) : (
        groups.map((g) => (
          <GroupSlider
            key={g.group || '\u0000'}
            group={g.group}
            joints={g.joints}
            all={shown}
            engaged={!!ours || !!extra?.cycle}
            shorts={shorts}
            windows={windows}
          />
        ))
      )}
    </section>
  )
}

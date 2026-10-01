// Spotlight tab: the 3D hand beside one joint at a time, shown big enough to
// read across a room while a loop runs.
//
// The point is a demo, not diagnosis: a visitor watches the hand move and the
// box tells them which joint is doing it, how far through its range, and how
// hard it is pulling. One joint at a time, cycling, because seventeen small
// readouts is a wall of numbers nobody reads.
//
// Sampling and drawing are separate rates. The bus is read far faster than
// the browser is told, because a current average is only as steady as the
// number of samples behind it, while a bar cannot move faster than a screen
// refresh.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { subscribeFrames } from '../../state/streamStore'
import { useOperationStore } from '../../state/operationStore'
import { HandScenePanel } from '../three/HandScenePanel'
import { Panel } from '../common/Panel'
import { SpotlightBox } from './SpotlightBox'

const DEFAULT_SAMPLE_HZ = 200
const DEFAULT_PUBLISH_HZ = 60
const DEFAULT_AVERAGE = 50
const DEFAULT_DWELL_S = 3

export function SpotlightView() {
  const joints = useAppStore((s) => s.handInfo?.joints)
  const setError = useAppStore((s) => s.setError)
  const operation = useOperationStore((s) => s.operation)

  const [dwellS, setDwellS] = useState(String(DEFAULT_DWELL_S))
  const [sampleHz, setSampleHz] = useState(String(DEFAULT_SAMPLE_HZ))
  const [publishHz, setPublishHz] = useState(String(DEFAULT_PUBLISH_HZ))
  const [average, setAverage] = useState(String(DEFAULT_AVERAGE))
  const [index, setIndex] = useState(0)
  const [tick, setTick] = useState(0)
  // '' cycles. 'finger:index' pins a finger and stacks its joints.
  // 'joint:index_mcp' pins one joint.
  const [pinned, setPinned] = useState('')
  const [highlight, setHighlight] = useState(true)

  // Only joints the config gives a range: the bar is a fraction of travel, so
  // a joint without one has nothing to be a fraction of.
  const spotlit = (joints ?? []).filter(
    (j) => j.motor_id !== null && j.rom && j.rom[1] !== j.rom[0],
  )

  // A loop is what this panel is for. Arming the sampler costs a real share
  // of a half-duplex bus, so it is not paid for while nothing is moving.
  const looping = Boolean(operation?.state === 'running' && operation?.kind)

  useEffect(() => {
    if (!looping) return
    const n = Math.max(1, Math.min(250, parseInt(sampleHz, 10) || DEFAULT_SAMPLE_HZ))
    const p = Math.max(1, Math.min(60, parseInt(publishHz, 10) || DEFAULT_PUBLISH_HZ))
    const w = Math.max(1, Math.min(1000, parseInt(average, 10) || DEFAULT_AVERAGE))
    void api.spotlight(true, n, p, w).catch((e) => setError(String((e as Error).message ?? e)))
    return () => {
      void api.spotlight(false, n, p, w).catch(() => undefined)
    }
  }, [looping, sampleHz, publishHz, average, setError])

  // Advance the spotlight on its own clock, independent of frame arrival.
  useEffect(() => {
    if (!looping || spotlit.length === 0 || pinned !== '') return
    const seconds = Math.max(0.5, Math.min(60, parseFloat(dwellS) || DEFAULT_DWELL_S))
    const id = window.setInterval(
      () => setIndex((i) => (i + 1) % spotlit.length),
      seconds * 1000,
    )
    return () => window.clearInterval(id)
  }, [looping, dwellS, spotlit.length, pinned])

  // Redraw on frames rather than polling: the store is mutated in place.
  useEffect(() => subscribeFrames(() => setTick((t) => t + 1)), [])

  // Which joints the boxes show. Pinning a finger stacks every joint on it,
  // which is what makes a single finger's motion legible: the joints move
  // together, so watching them apart tells you less than watching them stack.
  let shown: typeof spotlit
  if (pinned.startsWith('finger:')) {
    const finger = pinned.slice(7)
    shown = spotlit.filter((j) => fingerOf(j.id) === finger)
  } else if (pinned.startsWith('joint:')) {
    const id = pinned.slice(6)
    shown = spotlit.filter((j) => j.id === id)
  } else {
    const one = spotlit[index % Math.max(1, spotlit.length)]
    shown = one ? [one] : []
  }

  // Owned by this panel for exactly as long as it is mounted: left set, the
  // marks would follow the operator to the ordinary 3D tab.
  const lit = looping && highlight ? shown.map((j) => j.id) : []
  const litKey = lit.join(',')
  useEffect(() => {
    useAppStore.setState({ spotlightJoints: litKey ? litKey.split(',') : [] })
    return () => useAppStore.setState({ spotlightJoints: [] })
  }, [litKey])

  const fingers = Array.from(
    new Set(spotlit.map((j) => fingerOf(j.id)).filter(Boolean)),
  ) as string[]

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) 420px',
        gap: 12,
        alignItems: 'start',
      }}
    >
      <HandScenePanel height="calc(100vh - 240px)" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <select
          value={pinned}
          onChange={(e) => setPinned(e.target.value)}
          title={
            'cycle every joint in turn, or pin one finger (stacking its ' +
            'joints) or a single joint and stay on it'
          }
          style={{ fontSize: 11 }}
        >
          <option value="">cycle every joint</option>
          {fingers.map((f) => (
            <option key={f} value={`finger:${f}`}>
              finger — {f}
            </option>
          ))}
          {spotlit.map((j) => (
            <option key={j.id} value={`joint:${j.id}`}>
              joint — {j.id.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        {shown.length === 0 ? (
          <SpotlightBox joint={undefined} looping={looping} tick={tick} />
        ) : (
          shown.map((j) => (
            <SpotlightBox key={j.id} joint={j} looping={looping} tick={tick} />
          ))
        )}
        <Panel title="Spotlight settings">
          <div style={{ display: 'grid', gap: 6, fontSize: 11 }}>
            <Field
              label="joint every"
              suffix="s"
              value={dwellS}
              onChange={setDwellS}
              title="seconds before the box moves to the next joint"
            />
            <Field
              label="sample"
              suffix="Hz"
              value={sampleHz}
              onChange={setSampleHz}
              title={
                'how often the bus is read. Raising this sharpens the ' +
                'current average and the bar; it competes with whatever is ' +
                'driving the hand, so the achieved rate is shown above.'
              }
            />
            <Field
              label="draw"
              suffix="Hz"
              value={publishHz}
              onChange={setPublishHz}
              title={
                'how often the browser is told. Capped at 60 — a screen ' +
                'cannot show more, so anything above only costs bandwidth.'
              }
            />
            <label
              title={
                'mark the shown joint in the 3D view. Off leaves the scene '
                + 'alone, which is what you want when the hand itself is '
                + 'being filmed or the rings sit over what you are showing.'
              }
              style={{ display: 'flex', gap: 6, alignItems: 'center' }}
            >
              <span style={{ width: 92, color: 'var(--dim)' }}>highlight</span>
              <input
                type="checkbox"
                checked={highlight}
                onChange={(e) => setHighlight(e.target.checked)}
              />
              <span style={{ color: 'var(--dimmer)' }}>
                red mark in 3D
              </span>
            </label>
            <Field
              label="average over"
              suffix="samples"
              value={average}
              onChange={setAverage}
              title={
                'current samples behind the average. Present current is the ' +
                'instantaneous phase current of a PWM coil, so one sample ' +
                'says very little.'
              }
            />
          </div>
        </Panel>
      </div>
    </div>
  )
}

function Field({
  label,
  suffix,
  value,
  onChange,
  title,
}: {
  label: string
  suffix: string
  value: string
  onChange: (v: string) => void
  title: string
}) {
  return (
    <label
      title={title}
      style={{ display: 'flex', gap: 6, alignItems: 'center' }}
    >
      <span style={{ width: 92, color: 'var(--dim)' }}>{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 64 }}
      />
      <span style={{ color: 'var(--dimmer)' }}>{suffix}</span>
    </label>
  )
}


/** Finger a joint belongs to, or '' for the wrist, which belongs to none. */
function fingerOf(jointId: string): string {
  const [finger] = jointId.split('_')
  return finger === jointId ? '' : finger
}

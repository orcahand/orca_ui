// Endurance panel: what the hand settled to at every waypoint hold of a
// long looping test, plotted against hours since the test started (with
// cumulative cycles along the same axis). Range used per joint, holding
// current per motor (the slack signal on a hand without joint encoders —
// it falls as a tendon stretches and collapses when it snaps), fingertip
// force with dead/garbage intervals shaded, event markers, and the slack
// series from calibration checkpoints. Data comes from GET
// /api/endurance/tests/{id}: bucketed samples, full-resolution events and
// checkpoints; the raw per-hold rows are the CSV download.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/rest'
import type {
  EnduranceCheckpoint,
  EnduranceEvent,
  EnduranceSnapshot,
  EnduranceTest,
  EnduranceTestSummary,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useThemeStore } from '../../theme/themeStore'
import { Panel } from '../common/Panel'
import {
  FOLD_COLOR,
  SERIES_DARK,
  SERIES_LIGHT,
} from '../setup/CalibrationRomChart'

const REFRESH_ACTIVE_S = 5
const REFRESH_IDLE_S = 60
const WIDTH = 760
const MARGIN = { top: 14, right: 12, bottom: 34, left: 46 }
const EVENT_ROWS_COLLAPSED = 40

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

function fmtHours(seconds: number): string {
  const h = seconds / 3600
  if (h < 1) return `${Math.round(seconds / 60)}m`
  return `${h.toFixed(h < 10 ? 2 : 1)}h`
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

// Axis ticks in hours: a step that yields at most ~8 ticks.
function hourTicks(maxHours: number): number[] {
  const steps = [0.1, 0.25, 0.5, 1, 2, 3, 6, 12, 24, 48]
  const step = steps.find((s) => maxHours / s <= 8) ?? 48
  const ticks: number[] = []
  for (let t = 0; t <= maxHours + 1e-9; t += step) ticks.push(+t.toFixed(3))
  return ticks
}

function niceTicks(lo: number, hi: number, count = 5): number[] {
  const span = hi - lo
  if (!(span > 0)) return [lo]
  const raw = span / count
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count + 1) ?? mag * 10
  const ticks: number[] = []
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step)
    ticks.push(+t.toFixed(6))
  return ticks
}

// ----- series shapes ---------------------------------------------------------

interface Series {
  key: string
  label: string
  color: string
  width?: number
  points: [number, number | null][] // [seconds, value]
}

interface Band {
  color: string
  lower: [number, number | null][]
  upper: [number, number | null][]
}

interface Interval {
  from: number
  to: number
  color: string
  title: string
}

interface Marker {
  t: number
  color: string
  title: string
  tall?: boolean
}

interface Rule {
  y: number
  label: string
}

// Time-domain values (seconds since t0) are laid out as hours; `xMax` is
// the test's current extent so every chart shares one axis.
function TimeChart({
  title,
  unit,
  xMax,
  cycleAt,
  series,
  bands = [],
  intervals = [],
  markers = [],
  rules = [],
  height = 180,
  yMin,
}: {
  title: string
  unit: string
  xMax: number
  cycleAt: (seconds: number) => number | null
  series: Series[]
  bands?: Band[]
  intervals?: Interval[]
  markers?: Marker[]
  rules?: Rule[]
  height?: number
  yMin?: number
}) {
  const plotW = WIDTH - MARGIN.left - MARGIN.right
  const plotH = height - MARGIN.top - MARGIN.bottom
  const maxHours = Math.max(xMax / 3600, 1 / 60)
  const values: number[] = []
  for (const s of series) for (const [, v] of s.points) if (v !== null) values.push(v)
  for (const b of bands) {
    for (const [, v] of b.lower) if (v !== null) values.push(v)
    for (const [, v] of b.upper) if (v !== null) values.push(v)
  }
  for (const r of rules) values.push(r.y)
  let lo = values.length ? Math.min(...values) : 0
  let hi = values.length ? Math.max(...values) : 1
  if (yMin !== undefined) lo = Math.min(lo, yMin)
  if (hi - lo < 1e-6) {
    lo -= 1
    hi += 1
  }
  const pad = (hi - lo) * 0.08
  lo -= pad
  hi += pad
  const x = (seconds: number) => MARGIN.left + (seconds / 3600 / maxHours) * plotW
  const y = (value: number) => MARGIN.top + (1 - (value - lo) / (hi - lo)) * plotH

  const path = (points: [number, number | null][]) => {
    let d = ''
    let pen = false
    for (const [t, v] of points) {
      if (v === null) {
        pen = false
        continue
      }
      d += `${pen ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    }
    return d
  }
  const area = (band: Band) => {
    const up = band.upper.filter((p) => p[1] !== null) as [number, number][]
    const down = band.lower.filter((p) => p[1] !== null) as [number, number][]
    if (!up.length || !down.length) return ''
    const forward = up.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`)
    const back = [...down].reverse().map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`)
    return `M${forward.join('L')}L${back.join('L')}Z`
  }

  const empty = values.length === 0
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 10, color: 'var(--dim)', marginBottom: 2 }}>
        {title}
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        style={{ width: '100%', maxWidth: 1100, display: 'block' }}
        role="img"
        aria-label={title}
      >
        {intervals.map((iv, i) => (
          <rect
            key={`iv${i}`}
            x={x(iv.from)}
            y={MARGIN.top}
            width={Math.max(x(iv.to) - x(iv.from), 1.5)}
            height={plotH}
            fill={iv.color}
            opacity={0.18}
          >
            <title>{iv.title}</title>
          </rect>
        ))}
        {niceTicks(lo, hi).map((tick) => (
          <g key={`y${tick}`}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--panel-border)"
            />
            <text
              x={MARGIN.left - 4}
              y={y(tick) + 3}
              textAnchor="end"
              fontSize={9}
              fill="var(--dimmer)"
            >
              {+tick.toFixed(2)}
            </text>
          </g>
        ))}
        <text
          x={4}
          y={MARGIN.top - 4}
          fontSize={9}
          fill="var(--dimmer)"
        >
          {unit}
        </text>
        {hourTicks(maxHours).map((h) => {
          const cycle = cycleAt(h * 3600)
          return (
            <g key={`x${h}`}>
              <line
                x1={x(h * 3600)}
                x2={x(h * 3600)}
                y1={MARGIN.top}
                y2={MARGIN.top + plotH}
                stroke="var(--panel-border)"
              />
              <text
                x={x(h * 3600)}
                y={MARGIN.top + plotH + 11}
                textAnchor="middle"
                fontSize={9}
                fill="var(--dim)"
              >
                {h}h
              </text>
              {cycle !== null && (
                <text
                  x={x(h * 3600)}
                  y={MARGIN.top + plotH + 22}
                  textAnchor="middle"
                  fontSize={8}
                  fill="var(--dimmer)"
                >
                  c{cycle.toLocaleString()}
                </text>
              )}
            </g>
          )
        })}
        {rules.map((rule) => (
          <g key={`r${rule.label}`}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(rule.y)}
              y2={y(rule.y)}
              stroke="var(--dimmer)"
              strokeDasharray="3 3"
              opacity={0.7}
            />
            <text
              x={WIDTH - MARGIN.right - 2}
              y={y(rule.y) - 2}
              textAnchor="end"
              fontSize={8}
              fill="var(--dimmer)"
            >
              {rule.label}
            </text>
          </g>
        ))}
        {bands.map((band, i) => (
          <path key={`b${i}`} d={area(band)} fill={band.color} opacity={0.22} />
        ))}
        {series.map((s) => (
          <path
            key={s.key}
            d={path(s.points)}
            fill="none"
            stroke={s.color}
            strokeWidth={s.width ?? 1.4}
            strokeLinejoin="round"
          >
            <title>{s.label}</title>
          </path>
        ))}
        {markers.map((m, i) => (
          <g key={`m${i}`}>
            <line
              x1={x(m.t)}
              x2={x(m.t)}
              y1={MARGIN.top - (m.tall ? 8 : 4)}
              y2={m.tall ? MARGIN.top + plotH : MARGIN.top + 6}
              stroke={m.color}
              strokeWidth={m.tall ? 1 : 2}
              strokeDasharray={m.tall ? '2 3' : undefined}
            />
            <rect
              x={x(m.t) - 4}
              y={MARGIN.top - 10}
              width={8}
              height={plotH + 10}
              fill="transparent"
            >
              <title>{m.title}</title>
            </rect>
          </g>
        ))}
        {empty && (
          <text
            x={MARGIN.left + plotW / 2}
            y={MARGIN.top + plotH / 2}
            textAnchor="middle"
            fontSize={10}
            fill="var(--dimmer)"
          >
            no samples yet — they land at every waypoint hold of a replay,
            demo or stress test
          </text>
        )}
      </svg>
    </div>
  )
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        flexWrap: 'wrap',
        fontSize: 9,
        color: 'var(--dim)',
        marginTop: 2,
      }}
    >
      {items.map((item) => (
        <span key={item.label} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <span
            style={{
              width: 10,
              height: 3,
              background: item.color,
              display: 'inline-block',
            }}
          />
          {item.label}
        </span>
      ))}
    </div>
  )
}

// ----- derived data ----------------------------------------------------------

function eventTitle(event: EnduranceEvent): string {
  const leg = event.leg === null ? '' : ` · leg ${event.leg}`
  return `${fmtHours(event.t)} · cycle ${event.cycle}${leg} · ${event.subject}: ${event.detail}`
}

function severityColor(event: EnduranceEvent): string {
  if (event.severity === 'bad') return 'var(--err)'
  if (event.severity === 'ok') return 'var(--ok)'
  if (event.kind === 'note') return 'var(--warn)'
  return 'var(--dimmer)'
}

// Unhealthy stretches per subject: from a "bad" transition to the next "ok"
// one (or the end of the test while still bad).
function badIntervals(
  events: EnduranceEvent[],
  subject: (e: EnduranceEvent) => boolean,
  xMax: number,
  color: string,
): Interval[] {
  const open = new Map<string, EnduranceEvent>()
  const out: Interval[] = []
  for (const event of events) {
    if (!subject(event)) continue
    const opened = open.get(event.subject)
    if (event.severity === 'bad' && !opened) open.set(event.subject, event)
    else if (event.severity === 'ok' && opened) {
      out.push({
        from: opened.t,
        to: event.t,
        color,
        title: `${opened.subject} ${opened.detail} → recovered ${fmtHours(event.t)}`,
      })
      open.delete(event.subject)
    }
  }
  for (const opened of open.values())
    out.push({
      from: opened.t,
      to: xMax,
      color,
      title: `${opened.subject} ${opened.detail} (still)`,
    })
  return out
}

// Slack in joint degrees per checkpoint against the first one: extra motor
// travel between the hardstops, converted through the first checkpoint's
// motor-rad-per-joint-degree ratio.
function slackSeries(checkpoints: EnduranceCheckpoint[], joints: string[]) {
  const first = checkpoints.find((c) => Object.keys(c.travel_deg).length > 0)
  if (!first) return { rows: [] as { joint: string; points: [number, number | null][] }[], base: null }
  const rows = joints
    .filter((j) => first.travel_deg[j] !== undefined && first.ratio[j])
    .map((joint) => ({
      joint,
      points: checkpoints.map((cp): [number, number | null] => {
        const travel = cp.travel_deg[joint]
        if (travel === undefined) return [cp.t, null]
        const deltaRad = ((travel - first.travel_deg[joint]) * Math.PI) / 180
        return [cp.t, deltaRad / first.ratio[joint]]
      }),
    }))
  return { rows, base: first }
}

// ----- the panel -------------------------------------------------------------

export function EndurancePanel() {
  const handJoints = useAppStore((s) => s.handInfo?.joints)
  const dark = useThemeStore((s) => s.theme) === 'dark'
  const palette = dark ? SERIES_DARK : SERIES_LIGHT
  const [snapshot, setSnapshot] = useState<EnduranceSnapshot | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [test, setTest] = useState<EnduranceTest | null>(null)
  const [joint, setJoint] = useState<string>('')
  const [motor, setMotor] = useState<string>('')
  const [currentStat, setCurrentStat] = useState<'mean' | 'max'>('max')
  const [forceStat, setForceStat] = useState<'mean' | 'max'>('max')
  const [allEvents, setAllEvents] = useState(false)

  const loadList = () =>
    api
      .endurance()
      .then((s) => {
        setSnapshot(s)
        setSelected((current) => {
          if (current && s.tests.some((t) => t.id === current)) return current
          return s.active_id ?? s.tests[s.tests.length - 1]?.id ?? null
        })
      })
      .catch(() => undefined)

  useEffect(() => {
    void loadList()
  }, [])

  const selectedSummary: EnduranceTestSummary | undefined = snapshot?.tests.find(
    (t) => t.id === selected,
  )
  const active = Boolean(selectedSummary?.active)

  useEffect(() => {
    if (!selected) {
      setTest(null)
      return
    }
    let cancelled = false
    const load = () =>
      api
        .enduranceTest(selected)
        .then((t) => {
          if (!cancelled) setTest(t)
        })
        .catch(() => undefined)
    void load()
    const timer = window.setInterval(
      () => {
        void load()
        void loadList()
      },
      (active ? REFRESH_ACTIVE_S : REFRESH_IDLE_S) * 1000,
    )
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [selected, active])

  // Default the joint and motor selectors to the first joint the test knows.
  useEffect(() => {
    if (!test) return
    if (!joint || !test.joints.includes(joint)) setJoint(test.joints[0] ?? '')
  }, [test, joint])
  useEffect(() => {
    if (!test) return
    const forJoint = Object.entries(test.motor_joint).find(([, j]) => j === joint)?.[0]
    if (forJoint && (!motor || test.motor_joint[motor] !== joint)) setMotor(forJoint)
    else if (!motor && test.motors.length) setMotor(String(test.motors[0]))
  }, [test, joint, motor])

  const rom = useMemo(
    () => new Map((handJoints ?? []).map((j) => [j.id, j.rom])),
    [handJoints],
  )

  // Everything below is derived from the loaded test.
  const derived = useMemo(() => {
    if (!test) return null
    const b = test.buckets
    const mid = b.t0.map((t0, i) => (t0 + b.t1[i]) / 2)
    const xMax = Math.max(
      test.elapsed_s,
      b.t1[b.t1.length - 1] ?? 0,
      ...test.events.map((e) => e.t),
      ...test.checkpoints.map((c) => c.t),
      60,
    )
    const cycleAt = (seconds: number): number | null => {
      if (!b.t0.length) return null
      let cycle: number | null = null
      for (let i = 0; i < b.t0.length; i++) {
        if (b.t0[i] <= seconds) cycle = b.cycle1[i]
        else break
      }
      return cycle
    }
    const pointsOf = (values: (number | null)[] | undefined): [number, number | null][] =>
      (values ?? []).map((v, i) => [mid[i], v])
    const eventMarkers: Marker[] = test.events
      .filter((e) => e.kind !== 'test')
      .map((e) => ({ t: e.t, color: severityColor(e), title: eventTitle(e) }))
    const checkpointMarkers: Marker[] = test.checkpoints.map((c) => ({
      t: c.t,
      color: 'rgb(var(--accent-rgb))',
      tall: true,
      title:
        `calibration checkpoint · ${fmtHours(c.t)} · cycle ${c.cycle}` +
        (c.completed ? '' : ' · incomplete') +
        (c.problems.length ? `\n${c.problems.join('\n')}` : ''),
    }))
    return { mid, xMax, cycleAt, pointsOf, eventMarkers, checkpointMarkers }
  }, [test])

  const startTest = () => {
    const label =
      window.prompt(
        'Name for the endurance test (leave empty for an automatic name):',
        '',
      ) ?? undefined
    void api
      .enduranceStart(label || undefined)
      .then((t) => {
        setSelected(t.id)
        return loadList()
      })
      .catch(fail)
  }
  const stopTest = () => {
    if (!selected) return
    if (!window.confirm('Stop the running endurance test? Samples stop landing; the record is kept.')) return
    void api.enduranceStop(selected).then(loadList).catch(fail)
  }
  const renameTest = () => {
    if (!selected || !selectedSummary) return
    const label = window.prompt('New name for this test:', selectedSummary.label)
    if (label === null) return
    void api.enduranceRename(selected, label).then(loadList).catch(fail)
  }
  const addNote = () => {
    if (!selected) return
    const text = window.prompt(
      'Note to mark on the timeline (what you did or saw — a tendon replaced, a sensor reseated):',
      '',
    )
    if (!text) return
    void api
      .enduranceNote(selected, text)
      .then(() => api.enduranceTest(selected).then(setTest))
      .catch(fail)
  }
  const deleteTest = () => {
    if (!selected || !selectedSummary) return
    if (
      !window.confirm(
        `Delete endurance test "${selectedSummary.label}" — its summary and its raw sample file? This cannot be undone.`,
      )
    )
      return
    void api
      .enduranceDelete(selected)
      .then(() => {
        setSelected(null)
        return loadList()
      })
      .catch(fail)
  }

  const tests = snapshot?.tests ?? []
  const anyActive = Boolean(snapshot?.active_id)

  return (
    <Panel
      title="Endurance"
      toolbar={
        <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            disabled={anyActive}
            title={
              anyActive
                ? 'a test is running — stop it first'
                : 'start recording: t₀ is now; every waypoint hold of a replay, demo or stress test lands a sample'
            }
            onClick={startTest}
          >
            ▶ Start test
          </button>
          {selectedSummary && active && (
            <button className="btn btn-danger" onClick={stopTest} title="stop recording; the test is kept">
              ■ Stop
            </button>
          )}
          {selectedSummary && (
            <>
              <button className="btn btn-secondary" onClick={addNote} title="mark a note on the timeline">
                + Note
              </button>
              <button className="btn btn-secondary" onClick={renameTest}>
                Rename
              </button>
              <a
                className="btn btn-secondary"
                href={`/api/endurance/tests/${encodeURIComponent(selectedSummary.id)}/samples.csv`}
                download
                title="every per-hold sample: seconds since t₀, run, cycle, leg, settled angle per joint, holding current per motor, fingertip force per finger"
                style={{ textDecoration: 'none' }}
              >
                ⭳ CSV
              </a>
              <button
                className="btn btn-danger"
                onClick={deleteTest}
                title="delete this test and its raw samples"
              >
                Delete
              </button>
            </>
          )}
        </span>
      }
    >
      <p className="setup-copy dim">
        Records what the hand settled to at every waypoint hold — the read
        the hold already makes, so nothing is polled during motion — plus
        every event that changes the picture: operations starting and
        stopping, torque dropping, motor fault latches, tactile fingers
        freezing, zeroing, spiking or dropping out, and calibration
        checkpoints with the motor travel they measured.
      </p>

      {tests.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '6px 0 8px' }}>
          {tests.map((t) => (
            <button
              key={t.id}
              className={`view-tab ${t.id === selected ? 'active' : ''}`}
              onClick={() => setSelected(t.id)}
              title={`${fmtWhen(t.started_at)} → ${t.ended_at ? fmtWhen(t.ended_at) : 'running'}`}
            >
              {t.label}
              {t.active && <span style={{ color: 'var(--ok)' }}> ●</span>}
            </button>
          ))}
        </div>
      )}

      {!test || !derived ? (
        <div className="panel-empty">
          {tests.length === 0
            ? 'no endurance test recorded yet — press Start, then run the looping replay'
            : 'loading…'}
        </div>
      ) : (
        <>
          <div
            style={{
              display: 'flex',
              gap: 16,
              flexWrap: 'wrap',
              fontSize: 10,
              color: 'var(--dim)',
              marginBottom: 4,
            }}
          >
            <span>
              t₀ <span style={{ color: 'var(--text)' }}>{fmtWhen(test.started_at)}</span>
            </span>
            <span>
              elapsed <span style={{ color: 'var(--text)' }}>{fmtHours(test.elapsed_s)}</span>
              {test.ended_at && ' (stopped)'}
            </span>
            <span>
              cycles{' '}
              <span style={{ color: 'var(--text)' }}>{test.cycles_total.toLocaleString()}</span>
            </span>
            <span>
              holds sampled{' '}
              <span style={{ color: 'var(--text)' }}>{test.samples.toLocaleString()}</span>
            </span>
            <span>
              bucket <span style={{ color: 'var(--text)' }}>{fmtHours(test.bucket_s)}</span>
            </span>
            <span>
              events <span style={{ color: 'var(--text)' }}>{test.events.length}</span>
              {test.events_dropped > 0 && ` (+${test.events_dropped} dropped)`}
            </span>
            <span>
              checkpoints{' '}
              <span style={{ color: 'var(--text)' }}>{test.checkpoints.length}</span>
            </span>
            {test.latest && (
              <span>
                last hold{' '}
                <span style={{ color: 'var(--text)' }}>
                  {fmtHours(test.latest.t)} · cycle {test.latest.cycle}
                  {test.latest.leg !== null && ` · leg ${test.latest.leg}`}
                </span>
              </span>
            )}
          </div>

          {/* ----- range used per joint ----- */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, marginTop: 8 }}>
            <label style={{ color: 'var(--dim)' }}>
              joint{' '}
              <select
                value={joint}
                onChange={(e) => setJoint(e.target.value)}
                style={{ fontSize: 10 }}
              >
                {test.joints.map((j) => (
                  <option key={j} value={j}>
                    {j}
                  </option>
                ))}
              </select>
            </label>
            {test.latest?.angles[joint] != null && (
              <span style={{ color: 'var(--dim)' }}>
                last settled{' '}
                <span style={{ color: 'var(--text)' }}>{test.latest.angles[joint]!.toFixed(1)}°</span>
              </span>
            )}
          </div>
          <TimeChart
            title={`range used — ${joint}: settled angle at each hold, min…max per bucket (dashed = configured ROM)`}
            unit="deg"
            xMax={derived.xMax}
            cycleAt={derived.cycleAt}
            bands={[
              {
                color: 'rgb(var(--accent-rgb))',
                lower: derived.pointsOf(test.buckets.angle_min[joint]),
                upper: derived.pointsOf(test.buckets.angle_max[joint]),
              },
            ]}
            series={[
              {
                key: 'min',
                label: `${joint} lowest settled angle`,
                color: 'rgb(var(--accent-rgb))',
                points: derived.pointsOf(test.buckets.angle_min[joint]),
              },
              {
                key: 'max',
                label: `${joint} highest settled angle`,
                color: 'rgb(var(--accent-rgb))',
                points: derived.pointsOf(test.buckets.angle_max[joint]),
              },
            ]}
            rules={
              rom.get(joint)
                ? [
                    { y: rom.get(joint)![0], label: `ROM ${rom.get(joint)![0]}°` },
                    { y: rom.get(joint)![1], label: `ROM ${rom.get(joint)![1]}°` },
                  ]
                : []
            }
            markers={[...derived.eventMarkers, ...derived.checkpointMarkers]}
          />

          {/* ----- holding current per motor ----- */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, marginTop: 8 }}>
            <label style={{ color: 'var(--dim)' }}>
              highlight motor{' '}
              <select value={motor} onChange={(e) => setMotor(e.target.value)} style={{ fontSize: 10 }}>
                {test.motors.map((m) => (
                  <option key={m} value={String(m)}>
                    {m} {test.motor_joint[String(m)] ? `(${test.motor_joint[String(m)]})` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ color: 'var(--dim)' }}>
              per bucket{' '}
              <select
                value={currentStat}
                onChange={(e) => setCurrentStat(e.target.value as 'mean' | 'max')}
                style={{ fontSize: 10 }}
              >
                <option value="max">max</option>
                <option value="mean">mean</option>
              </select>
            </label>
            {test.latest?.currents[motor] != null && (
              <span style={{ color: 'var(--dim)' }}>
                last hold{' '}
                <span style={{ color: 'var(--text)' }}>{test.latest.currents[motor]!.toFixed(0)} mA</span>
              </span>
            )}
          </div>
          <TimeChart
            title="holding current per motor at the holds — falls as a tendon slackens, collapses when it snaps"
            unit="mA"
            xMax={derived.xMax}
            cycleAt={derived.cycleAt}
            yMin={0}
            series={[
              ...test.motors
                .filter((m) => String(m) !== motor)
                .map((m) => ({
                  key: String(m),
                  label: `motor ${m}${test.motor_joint[String(m)] ? ` (${test.motor_joint[String(m)]})` : ''}`,
                  color: FOLD_COLOR,
                  width: 0.8,
                  points: derived.pointsOf(
                    (currentStat === 'max' ? test.buckets.current_max : test.buckets.current_mean)[String(m)],
                  ),
                })),
              {
                key: `hl${motor}`,
                label: `motor ${motor}${test.motor_joint[motor] ? ` (${test.motor_joint[motor]})` : ''}`,
                color: 'rgb(var(--accent-rgb))',
                width: 2,
                points: derived.pointsOf(
                  (currentStat === 'max' ? test.buckets.current_max : test.buckets.current_mean)[motor],
                ),
              },
            ]}
            markers={[...derived.eventMarkers, ...derived.checkpointMarkers]}
          />
          <Legend
            items={[
              { label: `motor ${motor}${test.motor_joint[motor] ? ` (${test.motor_joint[motor]})` : ''}`, color: 'rgb(var(--accent-rgb))' },
              { label: 'other motors (hover a line for its id)', color: FOLD_COLOR },
            ]}
          />

          {/* ----- fingertip force ----- */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, marginTop: 8 }}>
            <label style={{ color: 'var(--dim)' }}>
              per bucket{' '}
              <select
                value={forceStat}
                onChange={(e) => setForceStat(e.target.value as 'mean' | 'max')}
                style={{ fontSize: 10 }}
              >
                <option value="max">max</option>
                <option value="mean">mean</option>
              </select>
            </label>
          </div>
          <TimeChart
            title="fingertip force at the holds — shaded: a finger reading dead or garbage (frozen, zero, NaN, spiky, dropped)"
            unit="N"
            xMax={derived.xMax}
            cycleAt={derived.cycleAt}
            yMin={0}
            series={test.fingers.map((finger, i) => ({
              key: finger,
              label: finger,
              color: palette[i % palette.length],
              points: derived.pointsOf(
                (forceStat === 'max' ? test.buckets.force_max : test.buckets.force_mean)[finger],
              ),
            }))}
            intervals={[
              ...badIntervals(
                test.events,
                (e) => e.kind === 'tactile' && e.subject.endsWith('fingertip'),
                derived.xMax,
                'var(--err)',
              ),
              ...badIntervals(
                test.events,
                (e) => e.kind === 'tactile' && e.subject === 'tactile stream',
                derived.xMax,
                'var(--warn)',
              ),
            ]}
            markers={[...derived.eventMarkers, ...derived.checkpointMarkers]}
          />
          <Legend
            items={test.fingers.map((finger, i) => ({
              label: finger,
              color: palette[i % palette.length],
            }))}
          />

          {/* ----- slack from calibration checkpoints ----- */}
          <SlackSection test={test} xMax={derived.xMax} cycleAt={derived.cycleAt} palette={palette} />

          {/* ----- events ----- */}
          <EventsTable
            events={test.events}
            all={allEvents}
            toggle={() => setAllEvents((v) => !v)}
          />
          <p className="setup-copy dim" style={{ marginTop: 8 }}>
            Stored in {snapshot?.path}; raw per-hold rows in endurance/{test.id}.csv
            next to it. Buckets are {fmtHours(test.bucket_s)} wide and double
            when the test outgrows 360 of them; events and checkpoints are
            kept at full resolution.
          </p>
        </>
      )}
    </Panel>
  )
}

function SlackSection({
  test,
  xMax,
  cycleAt,
  palette,
}: {
  test: EnduranceTest
  xMax: number
  cycleAt: (seconds: number) => number | null
  palette: string[]
}) {
  const { rows, base } = useMemo(
    () => slackSeries(test.checkpoints, test.joints),
    [test.checkpoints, test.joints],
  )
  if (!base) {
    return (
      <p className="setup-copy dim" style={{ marginTop: 10 }}>
        No calibration checkpoint yet — run a calibration while the test is
        active and its per-joint motor travel lands here; successive
        checkpoints plot as slack (extra travel between the hardstops, in
        joint degrees).
      </p>
    )
  }
  const last = test.checkpoints[test.checkpoints.length - 1]
  const colorOf = (i: number) => palette[i % palette.length]
  return (
    <>
      <TimeChart
        title={`slack from calibration checkpoints — extra motor travel between the hardstops vs the first checkpoint, in joint degrees (${test.checkpoints.length} checkpoint${test.checkpoints.length === 1 ? '' : 's'})`}
        unit="deg"
        xMax={xMax}
        cycleAt={cycleAt}
        series={rows.map((row, i) => ({
          key: row.joint,
          label: row.joint,
          color: colorOf(i),
          points: row.points,
        }))}
        rules={[{ y: 0, label: 'first checkpoint' }]}
        height={160}
      />
      <Legend items={rows.map((row, i) => ({ label: row.joint, color: colorOf(i) }))} />
      <table className="traj-table" style={{ fontSize: 10, marginTop: 6 }}>
        <thead>
          <tr>
            <th>joint</th>
            <th title="motor travel between the hardstops at the first checkpoint">travel at start</th>
            <th title="motor travel at the latest checkpoint">travel now</th>
            <th title="difference, in degrees of motor shaft">Δ motor</th>
            <th title="difference converted through the first checkpoint's motor-rad per joint-degree ratio">Δ joint</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const start = base.travel_deg[row.joint]
            const now = last.travel_deg[row.joint]
            const dJoint = row.points[row.points.length - 1][1]
            return (
              <tr key={row.joint}>
                <td className="traj-name">{row.joint}</td>
                <td>{start.toFixed(1)}°</td>
                <td>{now === undefined ? '—' : `${now.toFixed(1)}°`}</td>
                <td>{now === undefined ? '—' : `${(now - start).toFixed(1)}°`}</td>
                <td
                  style={{
                    color: dJoint !== null && Math.abs(dJoint) > 2 ? 'var(--warn)' : undefined,
                  }}
                >
                  {dJoint === null ? '—' : `${dJoint > 0 ? '+' : ''}${dJoint.toFixed(1)}°`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

function EventsTable({
  events,
  all,
  toggle,
}: {
  events: EnduranceEvent[]
  all: boolean
  toggle: () => void
}) {
  const newest = [...events].reverse()
  const shown = all ? newest : newest.slice(0, EVENT_ROWS_COLLAPSED)
  if (!events.length) {
    return (
      <p className="setup-copy dim" style={{ marginTop: 10 }}>
        no events yet
      </p>
    )
  }
  return (
    <details open style={{ marginTop: 10 }}>
      <summary style={{ cursor: 'pointer', fontSize: 10 }}>
        {events.length} event{events.length === 1 ? '' : 's'}
      </summary>
      <table className="traj-table" style={{ fontSize: 10, marginTop: 4 }}>
        <thead>
          <tr>
            <th>since t₀</th>
            <th>cycle</th>
            <th>leg</th>
            <th>kind</th>
            <th>subject</th>
            <th>what</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((event, i) => (
            <tr key={i}>
              <td style={{ color: 'var(--dimmer)' }}>{fmtHours(event.t)}</td>
              <td>{event.cycle.toLocaleString()}</td>
              <td>{event.leg ?? '—'}</td>
              <td>{event.kind}</td>
              <td>{event.subject}</td>
              <td style={{ color: severityColor(event) }}>{event.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {events.length > EVENT_ROWS_COLLAPSED && (
        <button className="btn btn-secondary" style={{ marginTop: 4 }} onClick={toggle}>
          {all ? `show latest ${EVENT_ROWS_COLLAPSED}` : `show all ${events.length}`}
        </button>
      )}
    </details>
  )
}

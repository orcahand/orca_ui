// Cockpit for the visual-calibration study's night protocol: numbered phases as progress
// rings with ETAs, the active phase's steps, and the accuracy answer once the analysis has one.
// Data: hand_study/server.py (:5010), proxied by /api/visual-calibration/study/*.
import { useEffect, useState } from 'react'
import './study.css'

type Status = 'waiting' | 'running' | 'fault' | 'done' | 'failed' | 'stopped'

interface Step {
  phase: string
  name: string
  label: string
  status: Status
  poses: number | null
  shot?: number
  skipped?: number
  solved?: number
  note?: string
  error?: string
  eta_start?: number
  eta_end?: number
  t0?: number
  t1?: number
}

interface Phase {
  key: string
  name: string
  status: Status
  steps: string[]
  eta_end: number | null
}

interface Stat { rms: number; p50: number; p95: number; max: number; mean?: number; mae?: number }

interface Protocol {
  tag: string
  hand: string
  state: string
  running: boolean
  started: number | null
  now: number
  eta_end: number
  phases: Phase[]
  steps: Step[]
  heartbeat: { age_s: number; note: string } | null
  faults: { t?: number; msg?: string; message?: string; where?: string }[]
  skin?: string
  registry?: {
    updated: string
    maps: string[]
    studies: {
      tag: string
      hand: string
      model: string
      skin: string
      date: string
      started: string | null
      ended: string | null
      state: string
      protocol: string
      rig: string
      test_set: string | null
      n_test: number | null
      best: string | null
      note?: string
      archive: string | null
      maps: Record<string, { joint_p50: number; tip_p50_mm: number | null; tip_mean_mm: number | null }>
    }[]
  } | null
  results: {
    fit_ablation?: {
      groups: Record<string, string>
      n_test: number
      variants: {
        key: string
        group: string
        label: string
        n_test: number
        silhouette_px?: number
        curve?: { mm: Record<string, Stat>; deg: Record<string, Stat> }
        stops?: { mm: Record<string, Stat>; deg: Record<string, Stat> }
      }[]
    }
    headline?: {
      set: string
      best: string
      maps: Record<string, { mm: Record<string, Stat>; deg: Record<string, Stat> }>
    }
  } | null
}

const BASE = '/api/visual-calibration/study'

const clock = (t?: number | null) =>
  t ? new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '–'

const dur = (s: number) => {
  const m = Math.max(0, Math.round(s / 60))
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : `${m} min`
}

function stepProgress(s: Step, now: number): number {
  if (s.status === 'done' || s.status === 'failed') return 1
  if (s.status !== 'running' && s.status !== 'fault') return 0
  if (s.poses && s.shot !== undefined) return Math.min(1, (s.shot + (s.skipped ?? 0)) / s.poses)
  if (s.eta_start && s.eta_end && s.eta_end > s.eta_start)
    return Math.min(0.95, Math.max(0.02, (now - s.eta_start) / (s.eta_end - s.eta_start)))
  return 0.05
}

function Ring({ n, frac, status }: { n: number; frac: number; status: Status }) {
  const r = 34
  const c = 2 * Math.PI * r
  return (
    <svg className={`study-ring ${status}`} viewBox="0 0 80 80">
      <circle className="track" cx="40" cy="40" r={r} />
      {frac > 0 && <circle
        className="bar"
        cx="40"
        cy="40"
        r={r}
        strokeDasharray={`${c * frac} ${c}`}
        transform="rotate(-90 40 40)"
      />}
      {status === 'running' && <circle className="spin" cx="40" cy="40" r={r} strokeDasharray={`${c * 0.08} ${c}`} />}
      <text x="40" y="47" textAnchor="middle">
        {status === 'done' ? '✓' : status === 'failed' ? '✕' : n}
      </text>
    </svg>
  )
}

// best = lowest fingertip median; joints as the median over all joints (an rms is ruled by the few failed fits)
function bestMap(p: Protocol) {
  const h = p.results?.headline
  if (!h) return undefined
  return Object.values(h.maps).reduce((a, b) => (b.mm.all.p50 < a.mm.all.p50 ? b : a))
}

function Wim({ p }: { p: Protocol }) {
  const best = bestMap(p)
  return (
    <div className="study-wim">
      @wim, the positional accuracy is:{' '}
      {best ? `${best.mm.all.p50.toFixed(1)} mm · ${best.deg.all?.p50.toFixed(1)}°` : '… (pending)'}
    </div>
  )
}

function Headline({ p }: { p: Protocol }) {
  const h = p.results?.headline
  const best = bestMap(p)
  if (!h || !best) return null
  const base = h.maps['packaged']
  return (
    <div className="study-headline">
      <div className="label">Positional accuracy</div>
      <div className="big">{best.mm.all.p50.toFixed(1)} mm</div>
      <div className="sub">
        fingertip, median · p95 {best.mm.all.p95.toFixed(1)} mm · joints {best.deg.all?.p50.toFixed(1)}° median
      </div>
      <div className="sub muted">{base && `packaged ${base.mm.all.p50.toFixed(1)} mm`}</div>
    </div>
  )
}

const MODEL_LABEL: Record<string, string> = {
  'ser-4485 stops': 'hard stops of ser-4485',
  'ser-7577 stops': 'hard stops of ser-7577',
  packaged: 'this hand, packaged stops',
  'own stops': 'this hand, own stops (fitted)',
  'per-joint curve': 'per-joint curve',
  'advanced: + current/compliance (full)': 'full model (+ current, compliance)',
  'LUT (coupled table)': 'coupled lookup table',
}

function Models({ p }: { p: Protocol }) {
  const h = p.results?.headline
  if (!h) return null
  const rows = Object.entries(h.maps)
  const best = Math.min(...rows.map(([, m]) => m.mm.all.p50))
  return (
    <div className="study-models">
      <div className="label">Models on held-out poses ({h.set})</div>
      <table>
        <thead>
          <tr>
            <th />
            <th>fingertip median</th>
            <th>fingertip mean</th>
            <th>fingertip p95</th>
            <th>joint median</th>
            <th>joint mean</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, m]) => (
            <tr key={k} className={m.mm.all.p50 === best ? 'best' : ''}>
              <td>{MODEL_LABEL[k] ?? k}</td>
              <td>{m.mm.all.p50.toFixed(2)} mm</td>
              <td>{m.mm.all.mean?.toFixed(2) ?? '–'} mm</td>
              <td>{m.mm.all.p95.toFixed(1)} mm</td>
              <td>{m.deg.all?.p50.toFixed(2) ?? '–'}°</td>
              <td>{m.deg.all?.mae?.toFixed(2) ?? '–'}°</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Ablation({ p }: { p: Protocol }) {
  const a = p.results?.fit_ablation
  if (!a) return null
  const m = (v: (typeof a.variants)[number]) => v.curve ?? v.stops
  const base = a.variants.find((v) => v.key === 'base')
  const b = base && m(base)
  return (
    <div className="study-models study-ablation">
      <div className="label">How the fit is done: each change against the baseline (held-out {a.n_test} poses, per-joint curve)</div>
      <table>
        <thead>
          <tr>
            <th />
            <th>fingertip median</th>
            <th>Δ</th>
            <th>joint median</th>
            <th>silhouette</th>
          </tr>
        </thead>
        <tbody>
          {a.variants.map((v) => {
            const s = m(v)
            const mm = s?.mm.all?.p50
            const d = mm !== undefined && b ? mm - b.mm.all.p50 : undefined
            return (
              <tr key={v.key} className={v.key === 'base' ? 'best' : v.key.startsWith('color') ? 'new' : ''}>
                <td title={v.label}>
                  <span className="grp">{a.groups[v.group] ?? v.group}</span> {v.label}
                </td>
                <td>{mm !== undefined ? `${mm.toFixed(2)} mm` : v.n_test ? '…' : 'running'}</td>
                <td className={d === undefined || v.key === 'base' ? '' : d < -0.02 ? 'good' : d > 0.02 ? 'bad' : ''}>
                  {d === undefined || v.key === 'base' ? '' : `${d > 0 ? '+' : ''}${d.toFixed(2)}`}
                </td>
                <td>{s?.deg.all ? `${s.deg.all.p50.toFixed(2)}°` : ''}</td>
                <td>{v.silhouette_px !== undefined ? `${v.silhouette_px.toFixed(1)} px` : ''}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Registry({ p }: { p: Protocol }) {
  const r = p.registry
  if (!r?.studies.length) return null
  return (
    <div className="study-models study-registry">
      <div className="label">
        Hands tested: held-out accuracy per mapping, joint median ° / fingertip median mm (registry.json, updated {r.updated})
      </div>
      <table>
        <thead>
          <tr>
            <th>date</th>
            <th>hand</th>
            <th>skin</th>
            <th>test poses</th>
            {r.maps.map((m) => <th key={m}>{m}</th>)}
          </tr>
        </thead>
        <tbody>
          {r.studies.map((s) => (
            <tr key={s.tag} className={s.tag === p.tag ? 'current' : ''}>
              <td title={`${s.started ?? s.date} → ${s.ended ?? '…'}`}>{s.date}</td>
              <td title={`${s.model} · ${s.rig} · ${s.protocol}${s.archive ? ` · ${s.archive}` : ''}`}>
                {s.hand} <span className="grp">{s.model.replace('orcahand-', '')}</span>
              </td>
              <td><span className={`skin ${s.skin}`}>{s.skin}</span></td>
              <td title={s.test_set ?? ''}>{s.n_test ?? '–'}{s.state !== 'done' ? ' …' : ''}</td>
              {r.maps.map((m) => {
                const v = s.maps[m]
                return (
                  <td key={m} className={s.best === m ? 'good' : ''} title={s.note}>
                    {v ? `${v.joint_p50.toFixed(2)}°${v.tip_p50_mm != null ? ` · ${v.tip_p50_mm.toFixed(2)} mm` : ''}` : '–'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function StudyView() {
  const [tags, setTags] = useState<string[]>([])
  const [tag, setTag] = useState<string | null>(null)
  const [p, setP] = useState<Protocol | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [notes, setNotes] = useState<{ t: number; who: string; text: string }[]>([])

  useEffect(() => {
    fetch(`${BASE}/protocols`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((l: string[]) => {
        setTags(l)
        setTag((t) => t ?? l.find((x) => !x.startsWith('dry')) ?? l[0] ?? null)
      })
      .catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    if (!tag) return
    let live = true
    const load = () =>
      fetch(`${BASE}/protocol/${tag}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
        .then((d: Protocol) => live && (setP(d), setErr(null)))
        .catch((e) => live && setErr(String(e)))
        .then(() => fetch(`${BASE}/notes/${tag}?limit=3`))
        .then((r) => (r && r.ok ? r.json() : []))
        .then((n) => live && setNotes(n))
        .catch(() => undefined)
    load()
    const id = setInterval(load, 3000)
    return () => {
      live = false
      clearInterval(id)
    }
  }, [tag])

  if (!p) return <div className="study-cockpit"><div className="study-msg">{err ?? 'loading…'}</div></div>

  const steps = Object.fromEntries(p.steps.map((s) => [s.name, s]))
  const active =
    p.phases.find((ph) => ph.status === 'running' || ph.status === 'fault') ??
    p.phases.find((ph) => ph.status === 'waiting') ??
    p.phases[p.phases.length - 1]
  const activeIdx = active ? p.phases.indexOf(active) : -1
  const fault = p.faults[p.faults.length - 1]
  const state = p.running ? 'running' : p.state

  return (
    <div className="study-cockpit">
      <header className="study-top">
        <div className="title">
          <span className="hand">{p.hand}</span>
          <span className={`pill ${state.replace(' ', '-')}`}>{state}</span>
          {p.skin && <span className={`skin ${p.skin}`}>{p.skin} skin</span>}
        </div>
        <div className="kpis">
          <div><span>elapsed</span>{p.started ? dur(p.now - p.started) : '–'}</div>
          <div><span>remaining</span>{dur(p.eta_end - p.now)}</div>
          <div><span>done at</span>{clock(p.eta_end)}</div>
        </div>
        {tags.length > 1 && (
          <select value={tag ?? ''} onChange={(e) => setTag(e.target.value)}>
            {tags.map((t) => <option key={t}>{t}</option>)}
          </select>
        )}
      </header>

      {notes.length > 0 && (
        <div className="study-feed">
          {notes.map((n, i) => (
            <div key={n.t} className={i === 0 ? 'latest' : 'old'}>
              <span className="when">{clock(n.t)}</span>
              <span className="who">{n.who}</span>
              <span className="text">{n.text}</span>
            </div>
          ))}
        </div>
      )}

      <Headline p={p} />
      {p.state === 'done' && (
        <div className="study-report">
          <Models p={p} />
          <Ablation p={p} />
        </div>
      )}
      <Registry p={p} />

      <ol className={`study-phases ${p.state === 'done' ? 'compact' : ''}`}>
        {p.phases.map((ph, i) => {
          const ss = ph.steps.map((n) => steps[n]).filter(Boolean)
          const frac = ss.length ? ss.reduce((a, s) => a + stepProgress(s, p.now), 0) / ss.length : 0
          return (
            <li key={ph.key} className={`${ph.status} ${i === activeIdx ? 'active' : ''}`}>
              <div className="phase-head">
                <Ring n={i + 1} frac={frac} status={ph.status} />
                <div>
                  <div className="name">{ph.name}</div>
                  <div className="eta">{ph.status === 'done' ? 'done' : `→ ${clock(ph.eta_end)}`}</div>
                </div>
              </div>
              <ol className="subs">
                {ss.map((s, j) => (
                  <li key={s.name} className={s.status} title={s.note || s.error || s.label}>
                    <span className="num">{i + 1}.{j + 1}</span>
                    <span className={`dot ${s.status}`} />
                    <span className="label">{s.label || s.name}</span>
                    <span className="prog">
                      {s.poses ? `${(s.shot ?? 0) + (s.skipped ?? 0)}/${s.poses}` : s.status === 'done' ? clock(s.t1) : clock(s.eta_start)}
                    </span>
                  </li>
                ))}
              </ol>
            </li>
          )
        })}
      </ol>

      <Wim p={p} />


      <footer className="study-foot">
        {fault ? (
          <span className="fault">⚠ {fault.where ? `${fault.where}: ` : ''}{fault.msg ?? fault.message ?? 'fault'} — recovering</span>
        ) : (
          <span className="muted">{p.heartbeat?.note ?? 'no faults'}</span>
        )}
        {err && <span className="fault">{err}</span>}
      </footer>
    </div>
  )
}

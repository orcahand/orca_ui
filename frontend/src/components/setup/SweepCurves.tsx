// The tension sweep per joint as curves along the travel: friction (solid)
// and static load (thin) against the share of the travel, the reference
// hand's curves dashed under them, departing stretches shaded. One small
// chart per joint, so the whole hand reads at a glance.

import type { SweepJointVerdict, SweepStatus } from '../../api/types'

const W = 260
const H = 110
const PAD = { l: 34, r: 8, t: 8, b: 18 }

const label = (joint: string) => joint.replace('_', ' ')

const WORD: Record<SweepStatus, string> = { none: '', ok: 'ok', slack: 'slack', over: 'tighter', under: 'tension', low: 'loose' }

// A joint's verdict as the sweep shows it: the word, then the friction share
// of the reference (or the difference in mA where the reference is too low for a share).
export function verdictText(v: SweepJointVerdict): string {
  if (v.status === 'none') return ''
  if (v.share != null) return `${WORD[v.status]} (${Math.round(v.share * 100)} %)`
  const d = v.friction_diff_ma
  return d == null ? WORD[v.status] : `${WORD[v.status]} (${d > 0 ? '+' : ''}${Math.round(d)} mA)`
}

// What each line and band of the chart is.
function Legend() {
  const swatch = (className: string) => (
    <svg className="sweep-swatch" viewBox="0 0 24 8" aria-hidden="true">
      <line className={className} x1="1" x2="23" y1="4" y2="4" />
    </svg>
  )
  return (
    <div className="sweep-legend">
      <span>{swatch('sweep-line friction')}friction, this hand</span>
      <span>{swatch('sweep-ref friction')}friction, reference</span>
      <span>{swatch('sweep-line static')}static load, this hand</span>
      <span>{swatch('sweep-ref static')}static load, reference</span>
      <span><i className="sweep-band below" />departs below the reference</span>
      <span><i className="sweep-band above" />departs above</span>
      <span className="dim">mA against the position along the travel, extend → flex</span>
    </div>
  )
}

function path(values: (number | null)[], sx: (i: number) => number, sy: (v: number) => number): string {
  let d = ''
  let pen = false
  values.forEach((v, i) => {
    if (v == null) {
      pen = false
      return
    }
    d += `${pen ? 'L' : 'M'} ${sx(i).toFixed(1)} ${sy(v).toFixed(1)} `
    pen = true
  })
  return d
}

export function SweepCurve({ joint, v, legend = false }: { joint: string; v: SweepJointVerdict; legend?: boolean }) {
  const all = [...v.friction, ...v.static, ...(v.ref_friction ?? []), ...(v.ref_static ?? [])].filter(
    (x): x is number => x != null,
  )
  const top = Math.max(10, ...all.map((x) => Math.abs(x))) * 1.1
  const n = v.friction.length
  const sx = (i: number) => PAD.l + ((i + 0.5) / n) * (W - PAD.l - PAD.r)
  const sy = (val: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - (val + top) / (2 * top))
  const y0 = sy(0)
  return (
    <figure className={`sweep-curve ${v.status}`}>
      <figcaption>
        <b>{label(joint)}</b>
        <span className={`probe-verdict ${v.status}`}>{verdictText(v)}</span>
        <small>
          friction {v.friction_ma ?? '—'}
          {v.ref_friction_ma != null ? ` / ${v.ref_friction_ma}` : ''} mA · static {v.static_ma ?? '—'}
          {v.ref_static_ma != null ? ` / ${v.ref_static_ma}` : ''} mA
        </small>
      </figcaption>
      {legend && <Legend />}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label(joint)} current along the travel`}>
        {v.stretches.map((st, i) => (
          <rect
            key={i}
            className={`sweep-stretch ${st.kind} ${st.diff_ma < 0 ? 'below' : 'above'}`}
            x={PAD.l + (st.from / 100) * (W - PAD.l - PAD.r)}
            y={PAD.t}
            width={((st.to - st.from) / 100) * (W - PAD.l - PAD.r)}
            height={H - PAD.t - PAD.b}
          />
        ))}
        <line className="sweep-axis" x1={PAD.l} x2={W - PAD.r} y1={y0} y2={y0} />
        <text className="sweep-tick" x={PAD.l - 4} y={sy(top / 1.1) + 3} textAnchor="end">
          {Math.round(top / 1.1)}
        </text>
        <text className="sweep-tick" x={PAD.l - 4} y={y0 + 3} textAnchor="end">
          0
        </text>
        <text className="sweep-tick" x={PAD.l} y={H - 5}>
          extend
        </text>
        <text className="sweep-tick" x={W - PAD.r} y={H - 5} textAnchor="end">
          flex · {Math.round(v.travel_deg)}°
        </text>
        {v.ref_friction && <path className="sweep-ref friction" d={path(v.ref_friction, sx, sy)} />}
        {v.ref_static && <path className="sweep-ref static" d={path(v.ref_static, sx, sy)} />}
        <path className="sweep-line static" d={path(v.static, sx, sy)} />
        <path className="sweep-line friction" d={path(v.friction, sx, sy)} />
      </svg>
    </figure>
  )
}

export function SweepCurves({ joints, verdict }: { joints: string[]; verdict: Record<string, SweepJointVerdict> }) {
  const shown = joints.filter((j) => verdict[j])
  if (!shown.length) return null
  return (
    <div className="sweep-curves">
      {shown.map((j) => (
        <SweepCurve key={j} joint={j} v={verdict[j]} />
      ))}
    </div>
  )
}

// Dashboard switch for the hand's joint mapping (the visual calibration study's maps, applied
// globally by the backend to every target and every published estimate), and a live readout of
// what orca_core believes each joint is (its motor estimate) against what the study says the
// joint really is. The switch moves nothing by itself: the next command uses it. Below it, every
// mapping of this hand (orca_core basic, main's stops, the fitted maps, other hands' stops) as a
// ghost-hand overlay row with its own visibility, colour and opacity, kept in this browser.

import { useEffect, useState } from 'react'
import { Panel } from '../common/Panel'
import { latest } from '../../state/streamStore'
import {
  autoColor,
  correctedPose,
  overlaySetting,
  useStudyMap,
  type OverlayRow,
  type StudyAccuracy,
  type StudyMapOption,
} from '../../state/studyMapStore'

const acc = (h: StudyAccuracy | null | undefined) => (h ? ` · held-out ${h.p50.toFixed(1)}° median / ${h.rms.toFixed(1)}° RMS` : '')
const optionText = (o: StudyMapOption) =>
  `${o.label} — ${o.approach}${o.params ? `, ${o.params} params` : ''}${acc(o.heldout)}${o.created ? ` · ${o.created}` : ''}`

const KIND = { basic: 'orca_core', main: 'main', fitted: 'fitted', 'other-hand': 'other hand' } as const

function OverlayList({ rows, active }: { rows: OverlayRow[]; active: string | null }) {
  const { overlaySettings, setOverlay, setAllOverlays } = useStudyMap()
  return (
    <div className="study-ov">
      <div className="study-ov-head">
        <strong>3D view: mappings as ghost hands</strong>
        <span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAllOverlays(true)}>all</button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAllOverlays(false)}>none</button>
        </span>
      </div>
      {rows.map((r) => {
        const o = overlaySetting(r.id, overlaySettings)
        const color = o.color ?? autoColor(rows, r.id)
        const drives = active != null && r.mode === active
        return (
          <div key={r.id} className={'study-ov-row' + (o.visible ? ' study-ov-on' : '') + (drives ? ' study-ov-drives' : '')}>
            <input
              type="checkbox"
              checked={o.visible}
              title="overlay in the 3D view"
              onChange={(e) => setOverlay(r.id, { visible: e.target.checked })}
            />
            <input
              type="color"
              value={color}
              title={o.color ? 'own colour' : 'automatic colour'}
              onChange={(e) => setOverlay(r.id, { color: e.target.value })}
            />
            <div className="study-ov-text">
              <div>
                <span className="study-ov-label" style={{ color }}>{r.label}</span>
                <span className="study-ov-kind">{KIND[r.kind]}</span>
                {drives && <span className="study-ov-badge">drives the hand</span>}
                {o.color && (
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOverlay(r.id, { color: null })}>
                    auto
                  </button>
                )}
              </div>
              <div className="study-ov-approach">
                {r.approach}
                {r.heldout ? ` · held-out ${r.heldout.rms.toFixed(2)}° RMS / ${r.heldout.p50.toFixed(2)}° median` : ''}
              </div>
            </div>
            <input
              type="range"
              min={5}
              max={100}
              value={Math.round(o.opacity * 100)}
              title="opacity"
              onChange={(e) => setOverlay(r.id, { opacity: Number(e.target.value) / 100, visible: true })}
            />
            <span className="study-ov-pct">{Math.round(o.opacity * 100)}%</span>
          </div>
        )
      })}
    </div>
  )
}

export function StudyCalibrationPanel() {
  const { state, error, load, setMode } = useStudyMap()
  const [pose, setPose] = useState<{ std: Record<string, number>; cor: Record<string, number> }>({ std: {}, cor: {} })

  useEffect(() => {
    void load()
    // Another window may switch it: the selection is global.
    const id = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(id)
  }, [load])
  useEffect(() => {
    const id = window.setInterval(() => {
      // Map on: the backend publishes the true angles, orca_core's own under `standard`.
      const j = latest.joints
      const mapped = Object.keys(j.standard).length > 0
      setPose(mapped ? { std: { ...j.standard }, cor: { ...j.estimate } } : { std: { ...j.estimate }, cor: correctedPose(j.estimate) })
    }, 250)
    return () => window.clearInterval(id)
  }, [])

  const rows = state?.overlays ?? []
  if (!state || (!state.available && rows.length === 0)) return null
  const joints = state.map?.joints ?? {}
  const on = state.enabled
  const shown = state.options.find((o) => o.name === (on ? state.mode : state.options[0]?.name))
  const coupled = Boolean(state.map?.coupled)
  const advanced = on && Boolean(state.map?.advanced)
  const std = state.standard ?? { label: 'Standard', approach: "orca_core linear map, this hand's config" }
  const stdAcc = state.options[0]?.heldout_standard
  return (
    <Panel
      title={`Visual calibration (study) · ${on ? shown?.label ?? state.mode : std.label} active`}
      toolbar={
        state.available && <label className="toggle-label" title="The hand's joint mapping for all of orca-ui">
          <select value={state.mode} onChange={(e) => void setMode(e.target.value)} style={{ maxWidth: '36em' }}>
            <option value="off">{`${std.label} — ${std.approach}${acc(stdAcc)}`}</option>
            {state.options.map((o) => (
              <option key={o.name} value={o.name}>
                {optionText(o)}
              </option>
            ))}
          </select>
        </label>
      }
    >
      <div className="study-cal">
        <p className={on ? 'study-cal-active study-cal-active-on' : 'study-cal-active'}>
          <strong>Active joint mapping{state.hand ? ` (${state.hand})` : ''}: </strong>
          {on && shown ? optionText(shown) : `${std.label} — ${std.approach}${acc(stdAcc)}`}
          <br />
          <span>
            {on
              ? 'Global: every joint target (sliders, poses, sequences, demos, teleop, REST/ws, neutral/zero) goes through it, and every joint estimate (3D view, recordings, pose capture) is the study\'s true angle.'
              : 'Global: off — targets and estimates are orca_core\'s own, exactly as without the study.'}
          </span>
        </p>
        {state.map && <p className="study-cal-note">
          {on
            ? 'Joint angles are the real joint angles. Each command is mapped through the study (photos of this hand) so the joint really gets there, clamped to the range it can reach.'
            : 'Switching on moves nothing; it applies from the next command. The choice is kept for this hand across restarts.'}{' '}
          {advanced
            ? 'Advanced model: tendon coupling and hysteresis (by the direction each joint moves) are corrected; tendon stretch under load is not (no current feed).'
            : 'Hysteresis is not corrected (up to 3–7° depending on the side a joint comes from).'} {state.hand ? `${state.hand}: ` : ''}study of {state.map.n_poses} poses, {state.map.created}.
          {(coupled || advanced) && !on && ' Coupled map: the readout shows each joint\'s own curve; once on, the full model.'}
        </p>}
        {rows.length > 0 && <OverlayList rows={rows} active={state.mode} />}
        {error && <p className="warn">{error}</p>}
        {state.map && <table>
          <thead>
            <tr>
              <th>joint</th>
              <th title="orca_core's motor estimate">standard</th>
              <th title="where the study says the joint really is">corrected</th>
              <th>Δ</th>
              <th title="the range the joint really reaches (study)">reach</th>
              <th>data</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(joints).map(([j, t]) => {
              const s = pose.std[j]
              const c = pose.cor[j]
              const d = s != null && c != null ? c - s : null
              return (
                <tr key={j} className={t.confidence === 'low' ? 'study-cal-low' : ''}>
                  <td>{j}</td>
                  <td>{s == null ? '—' : s.toFixed(1)}</td>
                  <td>{c == null ? '—' : c.toFixed(1)}</td>
                  <td className={d != null && Math.abs(d) > 3 ? 'warn' : ''}>{d == null ? '—' : (d >= 0 ? '+' : '') + d.toFixed(1)}</td>
                  <td title={`configured ${t.rom[0]}…${t.rom[1]}°`}>
                    {t.reach[0].toFixed(0)}…{t.reach[1].toFixed(0)}
                  </td>
                  <td title={t.noise_deg == null ? '' : `vision noise ${t.noise_deg.toFixed(1)}°`}>
                    {t.applied ? t.confidence : 'low: not corrected'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>}
      </div>
    </Panel>
  )
}

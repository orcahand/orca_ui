// What a solve found: 1a the lens, 1b where the camera is (next to the rig
// config's mount), the turning axis and the stop angles. Per-photo error bars
// under both; a photo over 1 px is marked.

import type { CameraMount, Session } from './api'
import { GOOD_PX, PHOTO_PX, fitOf, mountOf } from './solve'

function Bars({ perPhoto }: { perPhoto: Record<string, number> }) {
  const entries = Object.entries(perPhoto)
  if (!entries.length) return null
  const worst = Math.max(...entries.map(([, v]) => v))
  return (
    <div className="visual-cal-bars" title="Error per photo (px)">
      {entries.map(([name, px]) => (
        <div key={name} className="visual-cal-bar">
          <span>{+name.replace(/^stop_/, '')}°</span>
          <i className={px > PHOTO_PX ? 'warn' : ''} style={{ width: `${Math.min(100, (px / Math.max(PHOTO_PX, worst)) * 100)}%` }} />
          <em>{px.toFixed(2)}</em>
        </div>
      ))}
    </div>
  )
}

const signed = (v: number, d = 1) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`
const fmt = (v: number, unit: string) => `${v.toFixed(1)}${unit === '°' ? '' : ' '}${unit}`
const list = (v: number[], d = 2) => v.map((x) => x.toFixed(d)).join(', ')

export function Results({ session, cad }: { session: Session; cad: CameraMount | null }) {
  const r = session.result
  if (!r) return null
  const fit = fitOf(r)
  const found = mountOf(r)
  const corrections = Object.values(r.stop_angle_corrections ?? {})
  return (
    <div className="visual-cal-results">
      <div className="visual-cal-result-grid">
        {fit && (
          <>
            <span>fit</span>
            <b className={fit.reprojection_px > GOOD_PX ? 'warn' : 'ok'}>
              {fit.reprojection_px.toFixed(2)} px · {fit.points} corners · {fit.stops_used ?? fit.photos ?? session.photos.length} photos
            </b>
          </>
        )}
        <span>lens</span>
        <b>
          f {r.lens.fx.toFixed(0)} / {r.lens.fy.toFixed(0)} px · centre {r.lens.cx.toFixed(0)}, {r.lens.cy.toFixed(0)}
        </b>
        {!found && (
          <>
            <span>distortion</span>
            <b>{list(r.lens.distortion, 3)}</b>
          </>
        )}
        {r.axis && (
          <>
            <span>axis</span>
            <b>
              tilt {list(r.axis.tilt)}° · offset {list(r.axis.offset)} mm
            </b>
          </>
        )}
        {corrections.length > 0 && (
          <>
            <span>stops</span>
            <b>within ±{Math.max(...corrections.map(Math.abs)).toFixed(2)}° of nominal (bars on the dial)</b>
          </>
        )}
      </div>
      {found && (
        <table className="visual-cal-mount" title="The solved camera against the camera mount in the rig config">
          <thead>
            <tr>
              <th>camera</th>
              <th>found</th>
              <th>rig config</th>
              <th>off</th>
            </tr>
          </thead>
          <tbody>
            {(
              [
                ['distance', 'mm'],
                ['height', 'mm'],
                ['tilt', '°'],
              ] as const
            ).map(([k, unit]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{fmt(found[k], unit)}</td>
                <td>{cad ? fmt(cad[k], unit) : 'not set'}</td>
                <td className={cad && Math.abs(found[k] - cad[k]) > (unit === 'mm' ? 10 : 3) ? 'warn' : ''}>
                  {cad ? signed(found[k] - cad[k]) : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Bars perPhoto={r.per_photo_px} />
    </div>
  )
}

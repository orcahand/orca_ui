// 0 · Setup (docs/rig-setup.md): the one-time checks a newly built rig needs before 1 · Rig, in
// order, one card each with its status, what was found and the fix. Every card can run again
// safely; a rig already set up shows green from what local.yaml holds. The logic is the
// experiment's visual_calibration.setup, served by orca_ui/api/rig_setup.py.

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  setupApi,
  visualApi,
  type AlignResult,
  type CamId,
  type IdentifyResult,
  type ModelOverlay,
  type RigInfo,
  type SetupJob,
  type SetupStatus,
  type SetupSummary,
  type SetupWarning,
  type Turntable,
  type TurntableSetup,
  type UsbState,
} from './api'
import { CAM_LABEL } from './useRigCameras'

const ALIGN_MS = 2000
const JOB_MS = 500
const LIGHT_S = 10

type Lit = { serial: string; cam: CamId | null; until: number }

/** "Light up": one camera streams for LIGHT_S so its white LED is on; the label counts down. */
function LightButton({
  serial,
  cam,
  lit,
  onLight,
}: {
  serial: string | null
  cam: CamId | null
  lit: Lit | null
  onLight: (serial: string, cam: CamId | null) => void
}) {
  const [now, setNow] = useState(() => Date.now())
  const mine = !!lit && !!serial && lit.serial === serial && lit.until > now
  useEffect(() => {
    if (!mine) return
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [mine])
  useEffect(() => setNow(Date.now()), [lit])
  if (!serial) return null
  const left = mine && lit ? Math.ceil((lit.until - now) / 1000) : 0
  const who = cam ? CAM_LABEL[cam] : `serial ${serial}`
  return (
    <span className="rig-setup-light">
      <button
        className="btn btn-secondary btn-sm"
        onClick={() => onLight(serial, cam)}
        title="Stream this camera for a moment: its white light comes on"
      >
        Light up
      </button>
      {mine && (
        <span className="rig-setup-lit">
          {who}’s light is on for {left} s: the lit camera is {who}
        </span>
      )}
    </span>
  )
}

const TONE: Record<SetupStatus, string> = { ok: 'ok', warn: 'warn', error: 'error', 'not run': '' }

function Chip({ status }: { status: SetupStatus }) {
  return (
    <span className={`visual-cal-chip ${TONE[status]}`}>
      <i />
      {status}
    </span>
  )
}

function Card({
  n,
  title,
  status,
  at,
  actions,
  children,
}: {
  n: number
  title: string
  status: SetupStatus
  at?: unknown
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <section className={`rig-setup-card ${TONE[status]}`}>
      <header>
        <span className="rig-setup-num">{n}</span>
        <b>{title}</b>
        <Chip status={status} />
        {typeof at === 'string' && <span className="dim">{at.replace('T', ' ')}</span>}
        <span className="rig-setup-actions">{actions}</span>
      </header>
      {children}
    </section>
  )
}

function Findings({ warnings }: { warnings: SetupWarning[] }) {
  if (!warnings.length) return null
  return (
    <ul className="rig-setup-findings">
      {warnings.map((w, i) => (
        <li key={`${w.code}-${i}`} className={w.severity}>
          <b>{w.message}</b> {w.fix && <span>{w.fix}</span>}
        </li>
      ))}
    </ul>
  )
}

function Progress({ job, onStop }: { job: SetupJob; onStop: () => void }) {
  return (
    <div className="rig-setup-job">
      <div className="setup-progress">
        <div className="setup-progress-fill" style={{ width: `${Math.round(job.progress * 100)}%` }} />
      </div>
      <span className="dim">
        {job.kind}
        {job.camera ? ` ${CAM_LABEL[job.camera]}` : ''} · {job.note}
      </span>
      <button className="btn btn-secondary btn-sm" onClick={onStop}>
        Stop
      </button>
    </div>
  )
}

/** worst and mean sharpness (0..1, of each tile's best) per focus value: the chosen one marked. */
function FocusCurve({ curve, chosen }: { curve: [number, number, number][]; chosen: number }) {
  if (curve.length < 2) return null
  const W = 220
  const H = 70
  const xs = curve.map((r) => r[0])
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  const x = (v: number) => 4 + ((v - lo) / Math.max(1, hi - lo)) * (W - 8)
  const y = (v: number) => H - 4 - v * (H - 8)
  const line = (k: 1 | 2) => curve.map((r, i) => `${i ? 'L' : 'M'}${x(r[0]).toFixed(1)},${y(r[k] ?? 0).toFixed(1)}`).join('')
  return (
    <svg className="rig-setup-curve" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="focus sweep">
      <path d={line(2)} fill="none" stroke="var(--dim)" strokeWidth={1.5} />
      <path d={line(1)} fill="none" stroke="var(--accent)" strokeWidth={2} />
      <line x1={x(chosen)} x2={x(chosen)} y1={2} y2={H - 2} stroke="var(--ok)" strokeDasharray="3 3" />
      <text x={4} y={10} fontSize={9} fill="var(--dim)">
        worst (accent) · mean (grey) · focus {lo}…{hi}
      </text>
    </svg>
  )
}

/** Which screw does what on a camera mount: the 1/4" camera screw (tilt, aim), the slider bolt
 *  on the rail (distance) and the mast bolt (height). */
function MountDiagram() {
  return (
    <svg className="rig-setup-diagram" viewBox="0 0 260 150" width={260} height={150} role="img" aria-label="camera mount screws">
      <line x1={20} y1={135} x2={240} y2={135} stroke="var(--dim)" strokeWidth={6} />
      <text x={22} y={148} fontSize={9} fill="var(--dim)">rail: slider bolt sets the distance (holes)</text>
      <rect x={150} y={125} width={34} height={14} fill="none" stroke="var(--accent)" />
      <circle cx={167} cy={132} r={3} fill="var(--accent)" />
      <line x1={167} y1={125} x2={167} y2={45} stroke="var(--dim)" strokeWidth={5} />
      <circle cx={167} cy={80} r={3} fill="var(--accent)" />
      <text x={174} y={83} fontSize={9} fill="var(--dim)">mast bolt: height (holes)</text>
      <rect x={130} y={22} width={44} height={22} rx={4} fill="none" stroke="var(--fg, currentColor)" />
      <circle cx={167} cy={44} r={3} fill="var(--accent)" />
      <text x={20} y={18} fontSize={9} fill="var(--dim)">1/4&quot; camera screw: tilt and aim</text>
      <path d="M118 33 a14 14 0 0 1 0 -14" fill="none" stroke="var(--accent)" markerEnd="url(#arr)" />
      <defs>
        <marker id="arr" viewBox="0 0 6 6" refX={3} refY={3} markerWidth={5} markerHeight={5} orient="auto">
          <path d="M0 0 L6 3 L0 6 z" fill="var(--accent)" />
        </marker>
      </defs>
    </svg>
  )
}

export interface RigSetupProps {
  rig: RigInfo | null
  cams: CamId[]
  summary: SetupSummary | null
  refresh: () => Promise<unknown>
  tt: Turntable | null
  plateAngle: number
  rotation: Record<CamId, number>
  renderView: (cam: CamId, ghost: ModelOverlay | null) => ReactNode
  onSerials: () => void // the serials changed: reload the rig, check the streams again
  onTurntable: (t: Turntable) => void
}

export function RigSetup({ rig, cams, summary, refresh, tt, plateAngle, rotation, renderView, onSerials, onTurntable }: RigSetupProps) {
  const [usb, setUsb] = useState<UsbState | null>(null)
  const [table, setTable] = useState<TurntableSetup | null>(null)
  const [ident, setIdent] = useState<IdentifyResult | null>(null)
  const [swap, setSwap] = useState(false)
  const [align, setAlign] = useState<Partial<Record<CamId, AlignResult>>>({})
  const [aligning, setAligning] = useState<CamId | null>(null)
  const [ghost, setGhost] = useState<ModelOverlay | null>(null)
  const [job, setJob] = useState<SetupJob | null>(null)
  const [results, setResults] = useState<Record<string, SetupJob>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [lit, setLit] = useState<Lit | null>(null)
  const [error, setError] = useState<string | null>(null)
  const items = summary?.items

  const run = useCallback(
    async (what: string, fn: () => Promise<unknown>) => {
      setBusy(what)
      setError(null)
      try {
        await fn()
      } catch (e) {
        setError(`${what}: ${(e as Error).message}`)
      } finally {
        setBusy(null)
        void refresh()
      }
    },
    [refresh],
  )

  // A job running on the server (this page started it, or before a reload): follow it to its end.
  const running = job ?? summary?.jobs.find((j) => j.state === 'running') ?? null
  const runningId = running?.state === 'running' ? running.id : null
  useEffect(() => {
    if (!runningId) return
    let alive = true
    const id = window.setInterval(() => {
      setupApi.job(runningId).then((j) => {
        if (!alive) return
        if (j.state === 'running') return setJob(j)
        setJob(null)
        setResults((r) => ({ ...r, [`${j.kind}-${j.camera ?? ''}`]: j }))
        if (j.error) setError(`${j.kind}: ${j.error}`)
        void refresh()
      }, () => undefined)
    }, JOB_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [runningId, refresh])
  const startJob = (what: string, fn: () => Promise<SetupJob>) => run(what, async () => setJob(await fn()))

  // Align: a still by serial every ~2 s while a camera's guide is on, and the CAD ghost.
  const aligningRef = useRef(aligning)
  aligningRef.current = aligning
  useEffect(() => {
    if (!aligning) return
    let alive = true
    let timer = 0
    const tick = async () => {
      try {
        const r = await setupApi.align(aligning)
        if (alive) setAlign((a) => ({ ...a, [aligning]: r }))
      } catch (e) {
        if (alive) setError(`align ${CAM_LABEL[aligning]}: ${(e as Error).message}`)
      }
      if (alive) timer = window.setTimeout(tick, ALIGN_MS)
    }
    void tick()
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [aligning])
  const turn = aligning ? rotation[aligning] : 0
  useEffect(() => {
    if (!aligning) return setGhost(null)
    let alive = true
    visualApi.overlay(plateAngle, turn, aligning, true).then((m) => alive && setGhost(m), () => undefined)
    return () => {
      alive = false
    }
  }, [aligning, plateAngle, turn])

  const light = (serial: string, cam: CamId | null) =>
    void setupApi.light(cam ? { cam } : { serial }, LIGHT_S).then(
      (r) => setLit({ serial: r.serial, cam: r.camera, until: Date.now() + r.remaining_s * 1000 }),
      (e: Error) => setError(`light: ${e.message}`),
    )
  const status = (s: SetupStatus | undefined): SetupStatus => s ?? 'not run'
  const usbItem = usb ?? items?.usb.live ?? null
  const working = busy !== null || !!running

  // ---- identify: the proposal, swapped if asked
  const proposal = (() => {
    if (!ident) return null
    const a = { ...ident.identify.assignment }
    if (swap && a.a && a.b) return { a: a.b, b: a.a }
    return a
  })()
  const saveIdentity = (assignment: Partial<Record<CamId, string>>) =>
    run('saving the serials', async () => {
      await setupApi.saveIdentity(assignment)
      setIdent((i) => (i ? { ...i, saved: true, disagree: false, before: assignment } : i))
      onSerials()
    })

  const jobResult = (kind: string, c: CamId) => results[`${kind}-${c}`]?.result ?? items?.[kind as 'exposure']?.cameras?.[c] ?? null

  return (
    <div className="rig-setup">
      <div className={`rig-setup-summary ${summary?.ready ? 'ok' : 'warn'}`}>
        {summary?.ready ? (
          <b>Setup complete: ready for 1 · Rig.</b>
        ) : (
          <>
            <b>Not ready for 1 · Rig yet.</b>{' '}
            {summary?.blockers.length ? `Open: ${summary.blockers.join(' · ')}` : 'loading…'}
          </>
        )}
        {error && <div className="warn">{error}</div>}
        {busy && <div className="dim">{busy}…</div>}
      </div>

      <Card
        n={1}
        title="USB"
        status={status(usbItem?.status)}
        at={items?.usb.at}
        actions={
          <button className="btn btn-secondary btn-sm" disabled={working} onClick={() => run('USB', async () => setUsb(await setupApi.usb(true)))}>
            Check
          </button>
        }
      >
        {usbItem && (
          <>
            <table className="rig-setup-table">
              <thead>
                <tr>
                  <th>serial</th>
                  <th>mount</th>
                  <th>link</th>
                  <th>OpenCV</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {usbItem.cameras.map((c) => (
                  <tr key={String(c.serial)}>
                    <td>{c.serial ?? '?'}</td>
                    <td>{c.camera ? CAM_LABEL[c.camera] : 'not assigned'}</td>
                    <td className={c.usb3 === false ? 'warn' : ''}>
                      {c.link_mbps === null ? '?' : `${c.link_mbps} Mb/s`} {c.usb3 === false ? '(USB 2)' : c.usb3 ? '(USB 3)' : ''}
                    </td>
                    <td>{c.opencv_index ?? '—'}</td>
                    <td>
                      <LightButton serial={c.serial} cam={c.camera} lit={lit} onLight={light} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Findings warnings={usbItem.warnings} />
          </>
        )}
      </Card>

      <Card
        n={2}
        title="Turntable"
        status={status(table?.status ?? (items?.turntable.status as SetupStatus))}
        at={items?.turntable.at}
        actions={
          <button className="btn btn-secondary btn-sm" disabled={working} onClick={() => run('turntable', async () => setTable(await setupApi.turntable()))}>
            Check
          </button>
        }
      >
        {table && (
          <>
            <div className="dim">
              {table.board
                ? `board ${table.board.usb_serial ?? '?'} on ${table.board.port} · motor ${table.board.motor_id} (${table.board.model})`
                : table.mock
                  ? 'simulated turntable (--mock)'
                  : 'no board'}
              {' · '}
              {table.calibrated ? 'motor calibration present' : 'motor not calibrated'}
            </div>
            <Findings warnings={table.warnings} />
            {table.warnings.some((w) => w.code === 'turntable_uncalibrated' || w.code === 'turntable_other_motor') && (
              <div className="rig-setup-row">
                <button
                  className="btn btn-primary btn-sm"
                  disabled={working || !tt?.connected}
                  onClick={() =>
                    run('calibrating the motor', async () => {
                      const r = await visualApi.calibrateMotor()
                      onTurntable(r)
                      setTable(await setupApi.turntable())
                    })
                  }
                >
                  Calibrate motor
                </button>
                <span className="dim">
                  The plate turns slowly into its hard stop three times (that is 0°), then runs the whole travel to the other side and
                  back; every stop's motor position is saved to turntable_calibration.yaml. Nothing may be on the plate that can hit the
                  mast. The hand waits while it runs.
                </span>
              </div>
            )}
          </>
        )}
      </Card>

      <Card
        n={3}
        title="Identify cameras"
        status={status(ident?.status ?? (items?.identify.status as SetupStatus))}
        at={items?.identify.at}
        actions={
          <button
            className="btn btn-secondary btn-sm"
            disabled={working}
            onClick={() =>
              run('identifying the cameras', async () => {
                setSwap(false)
                const r = await setupApi.identify()
                setIdent(r)
                if (r.saved) onSerials()
              })
            }
          >
            Identify
          </button>
        }
      >
        <p className="dim">
          The calibration tower on the plate{tt?.calibrated ? ' (the plate parks at the reference stop first)' : ''}. Each camera’s
          pose from one still, matched to the mounts: which serial is cam A and which is cam B.
        </p>
        {ident && proposal && (
          <>
            <div className="rig-setup-ident">
              {ident.cameras.map((c) => {
                const as = (Object.entries(proposal) as [CamId, string][]).find(([, s]) => s === c.serial)?.[0]
                const nom = as ? ident.nominal[as] : undefined
                return (
                  <figure key={c.serial}>
                    {c.image && (
                      <img
                        src={`data:image/jpeg;base64,${c.image}`}
                        alt={`camera ${c.serial}`}
                        style={{ transform: `rotate(${as ? rotation[as] : 0}deg)` }}
                      />
                    )}
                    <figcaption>
                      <b>{as ? CAM_LABEL[as] : 'unassigned'}</b> · {c.serial}
                      <LightButton serial={c.serial} cam={c.configured_as} lit={lit} onLight={light} />
                      {c.error && <div className="warn">{c.error}</div>}
                      {c.pose ? (
                        <div>
                          distance {c.pose.radius_mm} mm{nom ? ` (mount ${nom.radius_mm})` : ''} · height {c.pose.height_mm} mm
                          {nom ? ` (${nom.height_mm})` : ''} · tilt {c.pose.tilt_down_deg}° down{nom ? ` (${nom.tilt_down_deg}°)` : ''} ·{' '}
                          {c.tiles} tiles
                        </div>
                      ) : (
                        !c.error && <div className="warn">too few tower corners seen</div>
                      )}
                    </figcaption>
                  </figure>
                )
              })}
            </div>
            {ident.saved ? (
              <p className="ok">Saved to local.yaml{ident.identify.confident ? ' (clearly told apart)' : ''}.</p>
            ) : ident.disagree ? (
              <div className="rig-setup-row">
                <span className="warn">
                  The serials set before ({Object.entries(ident.before).map(([c, s]) => `${CAM_LABEL[c as CamId]} ${s}`).join(', ')}) disagree
                  with what the cameras see now.
                </span>
                <button className="btn btn-primary btn-sm" disabled={working} onClick={() => saveIdentity(proposal)}>
                  Use what they see
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={working}
                  onClick={() => saveIdentity(Object.fromEntries(Object.entries(ident.before).filter(([, s]) => s)) as Partial<Record<CamId, string>>)}
                >
                  Keep the old serials
                </button>
              </div>
            ) : (
              <div className="rig-setup-row">
                <span className={ident.identify.confident ? '' : 'warn'}>
                  {ident.identify.confident ? 'Clearly told apart.' : `Not sure (margin ${ident.identify.margin ?? '?'}): check the images.`}
                </span>
                {proposal.a && proposal.b && (
                  <button className="btn btn-secondary btn-sm" onClick={() => setSwap((s) => !s)}>
                    Swap A and B
                  </button>
                )}
                <button className="btn btn-primary btn-sm" disabled={working || !Object.keys(proposal).length} onClick={() => saveIdentity(proposal)}>
                  Confirm and save
                </button>
              </div>
            )}
          </>
        )}
      </Card>

      <Card n={4} title="Align cameras" status={status(items?.align.status)}>
        <div className="rig-setup-align">
          <MountDiagram />
          <p className="dim">
            Over the live image: the tower as the mount in the config should see it (CAD ghost) and the tiles found. Move the camera
            until the instructions say to lock it.
          </p>
        </div>
        <div className="rig-setup-row">
          {cams.map((c) => (
            <button
              key={c}
              className={`btn btn-sm ${aligning === c ? 'btn-primary' : 'btn-secondary'}`}
              disabled={working && aligning !== c}
              onClick={() => setAligning((a) => (a === c ? null : c))}
            >
              {aligning === c ? `Stop ${CAM_LABEL[c]}` : `Align ${CAM_LABEL[c]}`}
              {' · '}
              {status(items?.align.cameras[c]?.status)}
            </button>
          ))}
        </div>
        {aligning && (
          <div className="rig-setup-align-live">
            <div className="rig-setup-view">{renderView(aligning, ghost)}</div>
            <AlignAdvice
              cam={aligning}
              r={align[aligning] ?? null}
              working={working}
              onKeep={(key, value) =>
                run(`mount.${key}`, async () => {
                  await setupApi.keepHole(aligning, key, value)
                  setAlign((a) => ({ ...a, [aligning]: undefined }))
                })
              }
              onCheck={() =>
                run('checking after locking', async () => {
                  const cam = aligning
                  const r = await setupApi.alignCheck(cam, true)
                  setAlign((a) => ({ ...a, [cam]: r }))
                })
              }
              passed={items?.align.cameras[aligning]?.status === 'ok'}
            />
          </div>
        )}
      </Card>

      {(['exposure', 'focus'] as const).map((kind, k) => (
        <Card key={kind} n={5 + k} title={kind === 'exposure' ? 'Exposure' : 'Focus'} status={status(items?.[kind].status)}>
          <p className="dim">
            {kind === 'exposure'
              ? 'The camera controls are locked first; then the shortest exposure in whole flicker periods that lights the tiles without clipping (gain 0). Saved to local.yaml and locked.'
              : 'After exposure: the focus where every visible tile is sharp together (every 8 units, then every 2 around the best). Saved to local.yaml and locked. 30–90 s.'}
          </p>
          {cams.map((c) => {
            const r = jobResult(kind, c) as Record<string, unknown> | null
            const blocked = kind === 'focus' && status(items?.exposure.cameras[c]?.status) === 'not run'
            return (
              <div key={c} className="rig-setup-row">
                <b>{CAM_LABEL[c]}</b>
                <Chip status={status(items?.[kind].cameras[c]?.status)} />
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={working || blocked}
                  title={blocked ? 'exposure first' : undefined}
                  onClick={() => startJob(`${kind} ${CAM_LABEL[c]}`, () => (kind === 'exposure' ? setupApi.exposure(c) : setupApi.focus(c)))}
                >
                  {r ? 'Run again' : 'Run'}
                </button>
                {r && kind === 'exposure' && (
                  <span>
                    exposure {String(r.exposure)} ({Number(r.exposure) / 10} ms)
                    {r.brightness !== undefined ? ` · brightness ${String(r.brightness)}${r.dim ? ' (dim: more light?)' : ''}` : ''}
                  </span>
                )}
                {r && kind === 'focus' && (
                  <span>
                    focus {String(r.focus)}
                    {r.worst !== undefined ? ` · worst tile ${String(r.worst)}, mean ${String(r.mean)}` : ''}
                  </span>
                )}
                {r && kind === 'focus' && Array.isArray(r.curve) && (
                  <FocusCurve curve={r.curve as [number, number, number][]} chosen={Number(r.focus)} />
                )}
              </div>
            )
          })}
          {running && running.kind === kind && <Progress job={running} onStop={() => void setupApi.cancel(running.id)} />}
        </Card>
      ))}

      <Card
        n={7}
        title="Tile tour"
        status={status(items?.tour.status as SetupStatus)}
        at={items?.tour.at}
        actions={
          <button
            className="btn btn-secondary btn-sm"
            disabled={working || !tt?.homed}
            title={tt?.homed ? undefined : 'connect and home (or calibrate) the turntable first'}
            onClick={() => startJob('tile tour', setupApi.tour)}
          >
            Run tour
          </button>
        }
      >
        <p className="dim">8 stops, 45° apart, a frame from every camera: every tile must be seen by some camera. Torque off after each move.</p>
        {running && running.kind === 'tour' && <Progress job={running} onStop={() => void setupApi.cancel(running.id)} />}
        <TourResult r={(results['tour-']?.result ?? items?.tour) as Record<string, unknown> | undefined} letters={rig?.letters ?? {}} />
      </Card>
    </div>
  )
}

function AlignAdvice({
  cam,
  r,
  working,
  passed,
  onKeep,
  onCheck,
}: {
  cam: CamId
  r: AlignResult | null
  working: boolean
  passed: boolean
  onKeep: (key: string, value: number) => void
  onCheck: () => void
}) {
  if (!r) return <p className="dim">measuring {CAM_LABEL[cam]}…</p>
  const p = r.placement
  const keep = p
    ? (Object.entries(p.holes) as ['distance' | 'height', number | null][]).filter(([k, v]) => v !== null && v !== p.want[k])
    : []
  return (
    <div className="rig-setup-advice">
      {p && (
        <div className="dim">
          found: distance {p.found.distance} mm (config {p.want.distance}) · height {p.found.height} mm ({p.want.height}) · tilt{' '}
          {p.found.tilt}° ({p.want.tilt}°) · tiles {r.tiles.join(' ')}
        </div>
      )}
      {!r.ok && (
        <ul>
          {r.advice.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
      {keep.map(([k, v]) => (
        <button key={k} className="btn btn-secondary btn-sm" disabled={working} onClick={() => onKeep(k, v!)}>
          Keep it here: set mount.{k}: {v} in local.yaml
        </button>
      ))}
      {r.ok && (r.status === 'ok' || passed) ? (
        <p className="ok rig-setup-lock">
          <b>{CAM_LABEL[cam]} is aligned and locked.</b>
        </p>
      ) : r.ok ? (
        <div className="rig-setup-lock">
          <b>Lock it now.</b> {p?.lock}
          <div className="rig-setup-row">
            <button className="btn btn-primary btn-sm" disabled={working} onClick={onCheck}>
              Check again after locking
            </button>
          </div>
        </div>
      ) : (
        r.status === 'error' && <p className="warn">It moved while locking: adjust again, then lock and check.</p>
      )}
    </div>
  )
}

function TourResult({ r, letters }: { r: Record<string, unknown> | undefined; letters: Record<string, string> }) {
  const stops = r?.stops as { stop: number; angle: number; cameras: Record<string, Record<string, number>> }[] | undefined
  if (!stops?.length) return null
  const all = Object.values(letters).sort()
  const missing = (r?.missing as string[]) ?? []
  return (
    <>
      <table className="rig-setup-table">
        <thead>
          <tr>
            <th>stop</th>
            {Object.keys(stops[0].cameras).map((c) => (
              <th key={c}>{CAM_LABEL[c as CamId] ?? c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stops.map((s) => (
            <tr key={s.stop}>
              <td>{s.stop}°</td>
              {Object.entries(s.cameras).map(([c, t]) => (
                <td key={c} className={Object.keys(t).length < 3 ? 'warn' : ''}>
                  {Object.keys(t).sort().join(' ') || '—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className={missing.length ? 'warn' : 'ok'}>
        {missing.length ? `not seen by any camera: ${missing.join(', ')}` : `all ${all.length} tiles seen`}
      </div>
      <Findings warnings={(r?.warnings as SetupWarning[]) ?? []} />
    </>
  )
}

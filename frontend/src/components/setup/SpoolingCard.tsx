// Spooling: attaching the tendons while the hand is still being built. The
// motors drive each finger to a hard stop in their own positive direction and
// hold it there through three hand steps — seat the bottom tendon, connect
// the top spool, screw it in. The last step is a torque wrench: the current
// limit drops to the ceiling and a motor whose shaft gives way under the
// screw is "at torque" — its tile flashes green and the card beeps.
//
// Two programs, picked before the run: wind and seat everything together and
// then take the top spools one at a time, or one motor through all three
// steps at a time. The grid shows the pack's two sides; the active spool
// wiggles so it can be found, a side can be wiggled to tell the sides apart,
// and a tile click makes that spool the one to work on. Per-motor state
// arrives in the snapshot extra (SpoolingExtra); prompts are answered through
// operation input.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type {
  OperationSnapshot,
  SpoolMotor,
  SpoolSide,
  SpoolState,
  SpoolingExtra,
  SpoolingMode,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isOperationActive,
  useOperationStore,
  useStartGate,
} from '../../state/operationStore'
import { HoverNote } from '../common/HoverNote'
import { beep, primeAudio } from './beep'
import { MotorPackMap } from './MotorPackMap'
import { SetupStep } from './TensionGuide'

const PHASES = ['winding', 'seating', 'attaching', 'tightening', 'released']
// Between the two sides the run parks here; the stepper shows it as done-so-far.
// The wrist has no spool and is not tendon driven, so it is never offered.
const FINGER_ORDER = ['thumb', 'index', 'middle', 'ring', 'pinky']
// Mirrors the backend ceiling: the input cannot ask for more.
const TIGHTEN_CEILING_MA = 100
const TIGHTEN_MIN_MA = 10
const WIND_MIN_MA = 50
// The pull a half-built hand's connectors take; the backend default.
const WIND_DEFAULT_MA = 150
// The console's temperature thresholds, in % of the rated maximum.
const TEMP_WARN_PCT = 70
const TEMP_ERR_PCT = 90

const STATE_LABEL: Record<SpoolState, string> = {
  pending: 'waiting',
  winding: 'winding',
  stalled: 'at hard stop',
  holding: 'holding',
  reached: '✓ at torque',
  over: 'too tight',
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

function fingerOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return FINGER_ORDER.includes(prefix) ? prefix : 'other'
}

function spoolingExtra(op: OperationSnapshot | null): SpoolingExtra | null {
  if (!op || op.kind !== 'spooling' || !op.extra) return null
  return op.extra as unknown as SpoolingExtra
}

const send = (value: string) => {
  primeAudio()
  void api.operationInput(value).catch(fail)
}

export function SpoolingCard() {
  const gate = useStartGate('motors')
  const handInfo = useAppStore((s) => s.handInfo)
  const operation = useOperationStore((s) => s.operation)

  const [mode, setMode] = useState<SpoolingMode>('all')
  const [tighten, setTighten] = useState(TIGHTEN_CEILING_MA)
  const [windValue, setWind] = useState(WIND_DEFAULT_MA)
  const [fingers, setFingers] = useState<Set<string>>(
    () => new Set(FINGER_ORDER),
  )

  const joints = useMemo(() => handInfo?.joints ?? [], [handInfo])
  const availableFingers = useMemo(
    () =>
      FINGER_ORDER.filter((finger) =>
        joints.some((joint) => fingerOf(joint.id) === finger),
      ),
    [joints],
  )
  const selectedJoints = joints
    .filter((joint) => fingers.has(fingerOf(joint.id)))
    .map((joint) => joint.id)

  const active =
    operation !== null &&
    operation.kind === 'spooling' &&
    isOperationActive(operation)
      ? operation
      : null
  const extra = spoolingExtra(active)
  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null

  // The torque-wrench click: every motor newly at torque beeps once and
  // restarts the card flash. Tiles flash on their own through CSS when
  // their state class changes.
  const reachedRef = useRef<Set<string>>(new Set())
  const [flashSeq, setFlashSeq] = useState(0)
  useEffect(() => {
    if (!extra) {
      reachedRef.current = new Set()
      return
    }
    const now = new Set(
      extra.motors
        .filter((m) => m.state === 'reached' || m.state === 'over')
        .map((m) => m.joint),
    )
    const fresh = [...now].some((joint) => !reachedRef.current.has(joint))
    reachedRef.current = now
    if (fresh) {
      beep()
      setFlashSeq((seq) => seq + 1)
    }
  }, [extra])

  const toggleFinger = (finger: string) =>
    setFingers((prev) => {
      const next = new Set(prev)
      if (next.has(finger)) next.delete(finger)
      else next.add(finger)
      return next
    })

  const start = () => {
    primeAudio()
    void api
      .operationStart('spooling', {
        mode,
        joints: selectedJoints,
        tighten_current_ma: tighten,
        wind_current_ma: windValue,
      })
      .catch(fail)
  }

  const tightenValid =
    Number.isFinite(tighten) &&
    tighten >= TIGHTEN_MIN_MA &&
    tighten <= TIGHTEN_CEILING_MA
  const windValid = Number.isFinite(windValue) && windValue >= WIND_MIN_MA
  const startBlocked =
    gate.blocked || selectedJoints.length === 0 || !tightenValid || !windValid
  const startReason =
    gate.reason ??
    (selectedJoints.length === 0
      ? 'pick at least one finger'
      : !tightenValid
        ? `torque must be ${TIGHTEN_MIN_MA}–${TIGHTEN_CEILING_MA} mA`
        : !windValid
          ? `winding current must be at least ${WIND_MIN_MA} mA`
          : null)

  return (
    <div className="setup-card setup-hero spool-card">
      {flashSeq > 0 && (
        <div key={flashSeq} className="spool-flash-overlay" />
      )}
      <div className="setup-hero-head">
        <div className="setup-card-title">Spooling</div>
        <span className="setup-badge">assembly</span>
        {extra && (
          <span className="spool-mode-tag">
            {extra.mode === 'all' ? 'wind all, then spool by spool' : 'one motor at a time'}
          </span>
        )}
      </div>
      <p className="setup-copy">
        For a hand that is still being built. Each motor pulls its finger to a
        hard stop and holds it there while you attach the tendons — first the
        bottom one, then the top one, screwed in against the motor like a
        torque wrench.
      </p>

      {active ? (
        <div className="spool-run">
          {extra && (
            <MotorPackMap
              extra={extra}
              onSelect={(joint) => send(`select:${joint}`)}
            />
          )}
          <div className="spool-run-main">
            <PhaseStepper current={active.phase} />
            {extra && <SpoolGrid extra={extra} />}
            <PhaseCallout
              operation={active}
              extra={extra}
              awaiting={awaiting}
            />
          </div>
        </div>
      ) : (
        <div className="setup-hero-body">
          <div className="setup-round-shape">
            <span className="setup-section-title">The steps</span>
            <ol className="setup-steps">
              <SetupStep n={1} title="Pull tendon through bottom spool and tie knot">
                Before starting: pull each bottom tendon through its bottom
                spool and tie it off. Leave the top tendon free; the motor
                winds the bottom one in itself.
              </SetupStep>
              <SetupStep n={2} title="Start — the motors drive to the hard stop">
                Each one winds its bottom tendon in until the finger sits on
                its hard stop. Keep clear until they stop.
              </SetupStep>
              <SetupStep n={3} title="Wiggle hand to remove slack on bottom tendon">
                The motors keep pulling at the winding current while you
                wiggle the hand. A finger pushed back is pulled back in. Press
                Next once nothing gives any more.
              </SetupStep>
              <SetupStep n={4} title="Connect the top spool">
                One motor at a time, side by side along the pack: the spool
                that is up next wiggles. Run its top tendon onto the top spool
                and pull it snug against the holding motor.
              </SetupStep>
              <SetupStep n={5} title="Screw in until it beeps">
                That motor's current limit drops to the torque setting. Turn
                the top spool in with the ratchet until the motor gives way:
                the tile turns green and the console beeps. Stop there, like a
                torque wrench clicking, and move to the next spool.
              </SetupStep>
            </ol>
          </div>

          <div className="setup-hero-side">
            <div className="spool-mode-switch">
              <button
                className={`finger-chip${mode === 'all' ? ' open has-selection' : ''}`}
                onClick={() => setMode('all')}
              >
                wind all, then spool by spool
              </button>
              <button
                className={`finger-chip${mode === 'one_by_one' ? ' open has-selection' : ''}`}
                onClick={() => setMode('one_by_one')}
              >
                one motor at a time
              </button>
              <HoverNote label="how it runs">
                {mode === 'all' ? (
                  <>
                    One side of the pack at a time, back first. That side's
                    motors wind to their hard stops and hold while you seat its
                    bottom tendons. Then its top spools go one at a time: the
                    motor that is up next wiggles, holds while you connect its
                    top spool, and drops to the torque limit while you screw
                    it in. When the side is done the front side starts the
                    same way. Click a motor on the map to work on a different
                    spool of the current side.
                  </>
                ) : (
                  <>
                    One motor at a time goes through all three steps while the
                    others wait with torque off. A finished motor keeps holding
                    its position at the torque limit so the joints next to it
                    stay put. Click a waiting tile to make it the next one.
                  </>
                )}
              </HoverNote>
            </div>
            <div className="spool-controls">
              <label className="joint-check">
                winding
                <input
                  className="spool-input"
                  type="number"
                  min={WIND_MIN_MA}
                  step={50}
                  value={windValue}
                  onChange={(e) => setWind(Number(e.target.value))}
                />
                mA
              </label>
              <label className="joint-check">
                torque
                <input
                  className="spool-input"
                  type="number"
                  min={TIGHTEN_MIN_MA}
                  max={TIGHTEN_CEILING_MA}
                  step={5}
                  value={tighten}
                  onChange={(e) => setTighten(Number(e.target.value))}
                />
                mA
              </label>
              <HoverNote label="what the currents mean">
                Winding is the pull: the current each motor winds in with and
                holds at until its top spool is screwed in. {WIND_DEFAULT_MA}{' '}
                mA by default — at the full operating current the motors pull
                themselves out of their connectors on a half-built hand — and
                capped at what the motor family allows. Torque is the current each motor holds
                against while you screw the top spool in; {TIGHTEN_CEILING_MA}{' '}
                mA is the ceiling and cannot be raised.
              </HoverNote>
            </div>
            <div className="finger-chip-row">
              {availableFingers.map((finger) => (
                <button
                  key={finger}
                  className={`finger-chip${
                    fingers.has(finger) ? ' has-selection open' : ''
                  }`}
                  onClick={() => toggleFinger(finger)}
                >
                  {finger}
                </button>
              ))}
            </div>
            <div className="setup-card-row">
              <button
                className="btn btn-primary btn-hero"
                disabled={startBlocked}
                title={startReason ?? undefined}
                onClick={start}
              >
                Start spooling
              </button>
            </div>
            {startReason && (
              <div className="setup-card-reason">{startReason}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function PhaseStepper({ current }: { current: string | null }) {
  const index =
    current === 'side_done' ? PHASES.length - 1 : current ? PHASES.indexOf(current) : -1
  return (
    <div className="phase-stepper">
      {PHASES.map((phase, i) => (
        <span
          key={phase}
          className={`phase-step${
            i === index ? ' active' : i < index ? ' done' : ''
          }`}
        >
          {phase}
        </span>
      ))}
    </div>
  )
}

function tempClass(temp: number | null, max: number | null): string {
  if (temp === null || max === null || max <= 0) return ''
  const pct = (temp / max) * 100
  if (pct >= TEMP_ERR_PCT) return ' err'
  if (pct >= TEMP_WARN_PCT) return ' warn'
  return ''
}

// The pack: one group of tiles per side, each with its own wiggle so the two
// sides can be told apart before the first spool is picked.
function SpoolGrid({ extra }: { extra: SpoolingExtra }) {
  const tightening = extra.phase === 'tightening'
  // A side wiggle needs motors that are already at their hard stop.
  const canWiggle =
    extra.phase === 'seating' ||
    extra.phase === 'attaching' ||
    extra.phase === 'tightening'
  const groups: { side: SpoolSide | null; motors: SpoolMotor[] }[] =
    extra.sides.length > 1
      ? extra.sides
          .map((side) => ({
            side,
            motors: extra.motors.filter((m) => m.side === side.id),
          }))
          .filter((group) => group.motors.length > 0)
      : [{ side: null, motors: extra.motors }]
  return (
    <div className="spool-sides">
      {groups.map(({ side, motors }) => (
        <div key={side?.id ?? 'all'} className="spool-side">
          {side && (
            <div className="spool-side-head">
              <span className="spool-side-label">
                {side.id === 'A' ? 'back' : 'front'} · side {side.id} · {side.label}
              </span>
              <button
                className="btn btn-secondary spool-side-wiggle"
                disabled={!canWiggle}
                title={`wiggle every motor on side ${side.id}`}
                onClick={() => send(`wiggle_side:${side.id}`)}
              >
                ≈ wiggle side {side.id}
              </button>
            </div>
          )}
          <div className="spool-grid">
            {motors.map((motor) => (
              <SpoolTile
                key={motor.joint}
                motor={motor}
                active={motor.joint === extra.active}
                maxTemp={extra.max_temp_c}
                tightening={tightening}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function SpoolTile({
  motor,
  active,
  maxTemp,
  tightening,
}: {
  motor: SpoolMotor
  active: boolean
  maxTemp: number | null
  tightening: boolean
}) {
  const limit = motor.limit_ma
  const pct = limit > 0 ? Math.min(100, (motor.current_ma / limit) * 100) : 0
  const pushed = Math.abs(motor.pushed_deg)
  const classes = [
    'spool-tile',
    motor.state,
    active ? 'active' : '',
    motor.done ? 'done' : '',
    motor.cooling ? 'cooling' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      className={classes}
      role="button"
      tabIndex={0}
      title="make this the spool to work on"
      onClick={() => send(`select:${motor.joint}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') send(`select:${motor.joint}`)
      }}
    >
      <div className="spool-tile-head">
        <span className="spool-joint">
          {active && <span className="spool-active-mark">▸ </span>}
          {motor.joint}
        </span>
        <span className="spool-id">M{motor.id}</span>
      </div>
      <div className="spool-bar">
        <div className="spool-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="spool-tile-foot">
        <span>
          {Math.round(motor.current_ma)} / {Math.round(limit)} mA
        </span>
        <span className="spool-state">
          {motor.cooling ? 'cooling' : STATE_LABEL[motor.state]}
        </span>
      </div>
      <div className="spool-tile-foot">
        <span className={`spool-temp${tempClass(motor.temp_c, maxTemp)}`}>
          {motor.temp_c !== null ? `${Math.round(motor.temp_c)} °C` : ''}
        </span>
        {motor.torque_drops > 0 && (
          <span className="spool-drift" title="went limp under load and was re-armed — check its connector">
            ⚡ limp ×{motor.torque_drops}
          </span>
        )}
        {tightening && pushed >= 1 && (
          <span className={motor.state === 'over' ? 'spool-drift' : ''}>
            {pushed.toFixed(0)}° off stop
          </span>
        )}
      </div>
    </div>
  )
}

// The instruction for the moment, with the buttons that move on.
function PhaseCallout({
  operation,
  extra,
  awaiting,
}: {
  operation: OperationSnapshot
  extra: SpoolingExtra | null
  awaiting: { prompt: string; options: string[] } | null
}) {
  const phase = operation.phase
  const option = awaiting?.options[0] ?? null
  const oneByOne = extra?.mode === 'one_by_one'
  const activeJoint = extra?.active ?? null
  const motors = extra?.motors ?? []
  const total = motors.length
  const done = motors.filter((m) => m.done).length
  const activeMotor = motors.find((m) => m.joint === activeJoint) ?? null
  const next = (label: string) =>
    option && (
      <button
        className="btn btn-info setup-release"
        onClick={() => send(option)}
      >
        {label}
      </button>
    )
  const wiggle = activeJoint && (
    <button
      className="btn btn-secondary"
      title={`wiggle ${activeJoint} so you can find it`}
      onClick={() => send('Wiggle')}
    >
      ≈ wiggle {activeJoint}
    </button>
  )
  const subject = oneByOne && activeJoint ? activeJoint : null

  if (phase === 'side_done') {
    return (
      <div className="setup-callout ok">
        <div className="setup-callout-title">✓ {awaiting?.prompt ?? 'Side done'}</div>
        <p className="setup-copy">
          The finished side keeps holding its spools at the torque limit.
          The next side's motors wind to their hard stops as soon as you
          start it — take your hands off the hand first.
        </p>
        {next(option ?? 'Start the next side')}
      </div>
    )
  }
  if (phase === 'seating') {
    return (
      <div className="setup-callout">
        <div className="setup-callout-title">
          ▸ Wiggle the slack out{subject ? ` — ${subject}` : ''}
        </div>
        <p className="setup-copy">
          {subject ? `${subject} is` : "This side's motors are"} pulling into
          the hard stop at {extra ? Math.round(extra.wind_current_ma) : '—'} mA. Wiggle
          the hand to work the slack out of the bottom tendon; a finger pushed
          back is pulled back in. Press Next once nothing gives any more.
          {!oneByOne &&
            ' Wiggle a side above to see which side of the pack you will start on.'}
        </p>
        {next(
          subject
            ? 'Slack is out — connect the top spool'
            : 'Slack is out — on to the top spools',
        )}
      </div>
    )
  }
  if (phase === 'attaching') {
    return (
      <div className="setup-callout">
        <div className="setup-callout-title">
          ▸ Connect the top spool — {activeJoint ?? '…'}
          {!oneByOne && total > 0 && ` · ${done + 1}/${total}`}
        </div>
        <p className="setup-copy">
          {activeJoint ?? 'The motor'} (motor {activeMotor?.id ?? '?'}) is
          holding firm and just wiggled. Run its top tendon onto the top spool
          and pull it snug by hand against the motor.
          {!oneByOne &&
            ' Click another motor on the map, or its tile, to start with that spool instead.'}
        </p>
        <div className="setup-card-row">
          {next('Top spool connected — start tightening')}
          {wiggle}
        </div>
      </div>
    )
  }
  if (phase === 'tightening') {
    const reached =
      activeMotor !== null &&
      (activeMotor.state === 'reached' || activeMotor.state === 'over')
    const limit = extra?.limit_ma ?? extra?.tighten_current_ma
    return (
      <div className={`setup-callout${reached ? ' ok' : ''}`}>
        <div className="setup-callout-title">
          ▸ Screw in {activeJoint ?? 'the top spool'}
          {!oneByOne && total > 0 && ` · ${done + 1}/${total}`}
          {reached && ' · at torque'}
        </div>
        <p className="setup-copy">
          {activeJoint ?? 'The motor'} is holding at {limit != null ? Math.round(limit) : '—'}{' '}
          mA. Turn its top spool in with the ratchet until the motor gives
          way: the tile turns green and the console beeps — that is the click
          of the torque wrench. Stop there. A tile marked too tight has been
          pushed well past the click: back the spool off until it turns green
          again.
        </p>
        <div className="setup-card-row">
          {next(
            option === 'Done'
              ? 'Done — release the motors'
              : reached
                ? 'Next spool'
                : 'Skip to the next spool',
          )}
          {wiggle}
        </div>
      </div>
    )
  }
  return (
    <>
      <div className="setup-card-detail">
        {phase ?? 'starting'}
        {operation.detail ? ` — ${operation.detail}` : ''}
      </div>
      {phase === 'winding' && (
        <p className="setup-copy dim">
          {subject ? `${subject} is` : 'The motors are'} driving to the hard
          stop. Keep hands and objects clear.
        </p>
      )}
    </>
  )
}

// Slim electrical-health strip at the top of the dashboard: the overall
// score from the Tkinter monitor (every encoder slot, motor and tactile
// sensor counts one point) plus per-link quality. Detail is fused into the
// panels below — encoder verdict dots, motor presence dots, tactile counts.
// Every degraded segment is clickable: the popover lists exactly which
// items are broken, why, and what to check.

import { useRef, useState } from 'react'
import { FINGERS } from '../../api/types'
import { useSensorsHealth } from '../../hooks/useSensorsHealth'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { Diagnosable, type Diagnosis } from '../common/Diagnosable'
import {
  encoderDiagnosis,
  linkDiagnosis,
  motorDiagnosis,
  TEMP_ERR_FRACTION,
  TEMP_WARN_FRACTION,
  tactileDiagnosis,
  thermalDiagnosis,
} from './monitorShared'

// A count in the strip; when something behind it is broken it becomes a
// click target listing the broken items.
function Segment({
  text,
  ok,
  diagnoses,
  align,
  color,
}: {
  text: string
  ok: boolean
  diagnoses: Diagnosis[]
  align?: 'left' | 'right'
  color?: string
}) {
  const broken = diagnoses.filter((d) => !d.ok)
  const body = (
    <span
      style={{
        color: color ?? (ok ? 'var(--dim)' : 'var(--warn)'),
        textDecoration: broken.length > 0 ? 'underline dotted' : undefined,
        textUnderlineOffset: 3,
      }}
      title={broken.length > 0 ? 'click to see what is not working' : undefined}
    >
      {text}
    </span>
  )
  if (broken.length === 0) return body
  return (
    <Diagnosable diagnoses={broken} label={`diagnose ${text}`} align={align}>
      {body}
    </Diagnosable>
  )
}

export function HealthSummary() {
  const health = useSensorsHealth()
  const status = useAppStore((s) => s.status)
  const joints = useAppStore((s) => s.handInfo?.joints)

  // Which motor ids answer telemetry reads (temps/currents payloads).
  const [motorsAnswering, setMotorsAnswering] = useState<string[] | null>(null)
  const lastIds = useRef('')
  // Whole degrees only: the strip re-renders on change and the raw reading
  // dithers by tenths at 1 Hz.
  const [temps, setTemps] = useState<Record<string, number>>({})
  const [maxTempC, setMaxTempC] = useState<number | null>(null)
  const lastTemps = useRef('')
  useStreamFrame((frames) => {
    const ids = Array.from(
      new Set([
        ...Object.keys(frames.motors.temps),
        ...Object.keys(frames.motors.currents),
      ]),
    ).sort((a, b) => Number(a) - Number(b))
    const json = ids.join(',')
    if (json !== lastIds.current) {
      lastIds.current = json
      setMotorsAnswering(ids.length > 0 ? ids : null)
    }

    const rounded: Record<string, number> = {}
    for (const [id, t] of Object.entries(frames.motors.temps)) {
      rounded[id] = Math.round(t)
    }
    const key = JSON.stringify(rounded) + String(frames.motors.maxTempC)
    if (key !== lastTemps.current) {
      lastTemps.current = key
      setTemps(rounded)
      setMaxTempC(frames.motors.maxTempC)
    }
  })

  const caps = status?.capabilities
  if (!caps || !health) return null

  const enc = health.encoders
  const tac = health.tactile
  const motorJoints = (joints ?? []).filter(
    (j) => j.motor_id !== null && j.motor_id !== undefined,
  )
  const motorTotal = motorJoints.length
  const showMotors = caps.motors && motorTotal > 0
  const answering = new Set(motorsAnswering ?? [])

  let ok = 0
  let total = 0
  if (enc) {
    ok += enc.live
    total += enc.total
  }
  if (showMotors) {
    ok += motorsAnswering?.length ?? 0
    total += motorTotal
  }
  const tacConnected = tac
    ? Object.values(tac.fingers).filter((f) => f.connected).length
    : 0
  if (tac) {
    ok += tacConnected
    total += FINGERS.length
  }
  if (total === 0) return null

  const pct = Math.round((100 * ok) / total)
  const pctColor =
    ok === total ? 'var(--ok)' : ok > 0 ? 'var(--warn)' : 'var(--err)'

  const encDiagnoses = enc
    ? Object.entries(enc.joints)
        .filter(
          ([joint, h]) =>
            h.verdict !== 'live' || enc.suppressed?.[joint] != null,
        )
        .map(([joint, h]) =>
          encoderDiagnosis(
            joint,
            h,
            enc.suppressed?.[joint] ?? null,
            enc.restore_after_s,
          ),
        )
    : []
  const motorDiagnoses =
    showMotors && motorsAnswering !== null
      ? motorJoints
          .filter((j) => !answering.has(String(j.motor_id)))
          .map((j) => motorDiagnosis(String(j.motor_id), j.id, false))
      : []
  const tacDiagnoses = tac
    ? FINGERS.filter((f) => !(tac.fingers[f]?.connected ?? false)).map((f) =>
        tactileDiagnosis(f, false),
      )
    : []

  // Hottest motor on the bus, and everything running warm behind it.
  const jointForMotor = new Map<string, string>(
    motorJoints.map((j) => [String(j.motor_id), j.id] as [string, string]),
  )
  const tempEntries = Object.entries(temps)
  const ratedMax = maxTempC ?? 70
  const hottest = tempEntries.reduce<[string, number] | null>(
    (best, e) => (best === null || e[1] > best[1] ? e : best),
    null,
  )
  const warmEntries = tempEntries
    .filter(([, t]) => t >= ratedMax * TEMP_WARN_FRACTION)
    .sort((a, b) => b[1] - a[1])
  const thermalDiagnoses = warmEntries.map(([id, t]) =>
    thermalDiagnosis(id, jointForMotor.get(id) ?? null, t, ratedMax),
  )
  const thermalColor =
    hottest === null
      ? 'var(--dim)'
      : hottest[1] >= ratedMax * TEMP_ERR_FRACTION
        ? 'var(--err)'
        : hottest[1] >= ratedMax * TEMP_WARN_FRACTION
          ? 'var(--warn)'
          : 'var(--dim)'

  const links = Object.entries(health.links)
  const linksDirty = links.filter(
    ([, l]) => l.port_dead || !l.connected || l.resyncs > 0 || l.bad_lrc > 0,
  )
  const linkDiagnoses = linksDirty.map(([name, l]) => linkDiagnosis(name, l))

  const sep = <span style={{ color: 'var(--dimmer)' }}>·</span>

  return (
    <section
      className="panel"
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 10,
        flexWrap: 'wrap',
        fontSize: 10,
        padding: '8px 12px',
      }}
    >
      <span
        style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: 1,
          textTransform: 'uppercase',
          color: 'var(--muted)',
        }}
      >
        Electrical
      </span>
      <span style={{ fontWeight: 700, fontSize: 13, color: pctColor }}>
        {pct}%
      </span>
      <span style={{ color: 'var(--dim)' }}>
        {ok}/{total} working
      </span>
      {enc && (
        <>
          {sep}
          <Segment
            text={`encoders ${enc.live}/${enc.total} @ ${enc.hz.toFixed(0)} Hz`}
            ok={enc.live === enc.total && encDiagnoses.length === 0}
            diagnoses={encDiagnoses}
          />
        </>
      )}
      {showMotors && (
        <>
          {sep}
          <Segment
            text={`motors ${motorsAnswering?.length ?? '--'}/${motorTotal}`}
            ok={(motorsAnswering?.length ?? 0) === motorTotal}
            diagnoses={motorDiagnoses}
          />
        </>
      )}
      {showMotors && hottest !== null && (
        <>
          {sep}
          <Segment
            text={
              `${hottest[1]} °C max (` +
              (jointForMotor.get(hottest[0]) ?? `motor ${hottest[0]}`) +
              ')' +
              (warmEntries.length > 1 ? ` · ${warmEntries.length} warm` : '')
            }
            ok={warmEntries.length === 0}
            diagnoses={thermalDiagnoses}
            color={thermalColor}
          />
        </>
      )}
      {tac && (
        <>
          {sep}
          <Segment
            text={`tactile ${tacConnected}/${FINGERS.length} @ ${tac.hz.toFixed(0)} Hz`}
            ok={tacConnected === FINGERS.length}
            diagnoses={tacDiagnoses}
          />
        </>
      )}
      <span style={{ marginLeft: 'auto' }}>
        <Segment
          text={
            linksDirty.length === 0
              ? 'links clean'
              : linksDirty
                  .map(([name, l]) =>
                    l.port_dead
                      ? `${name} link: port dead`
                      : !l.connected
                        ? `${name} link: down`
                        : `${name} link: ${l.resyncs} resyncs, ${l.bad_lrc} bad lrc`,
                  )
                  .join(' · ')
          }
          ok={linksDirty.length === 0}
          diagnoses={linkDiagnoses}
          align="right"
        />
      </span>
    </section>
  )
}

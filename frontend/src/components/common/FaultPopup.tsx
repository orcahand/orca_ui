// A motor with a latched hardware error answers the bus and acks torque
// enable but never energizes: it looks "seen" and holds nothing. This pops up
// the moment one is reported, from either source — the running maintenance
// routine (which holds the motor bus and clears the latch through an
// operation input) or the live session's fault sweep (cleared through the
// reboot endpoint, torque off first) — with the one click that fixes it.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { GuidedTensionExtra, HwErrorInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { RebootButton } from '../motors/RebootButton'

interface Fault {
  // The same latch keeps its key whichever source reports it, so a
  // dismissal survives the hand-over between a routine and the live session.
  key: string
  motor: string
  joint: string | null
  info: HwErrorInfo
  relatched: boolean
  // 'operation': the routine holds the bus; 'session': the live hand does.
  source: 'operation' | 'session'
}

function faultKey(motor: string | number, flags: string[], relatched = false): string {
  return `${motor}:${flags.join('+')}${relatched ? ':again' : ''}`
}

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function FaultPopup() {
  const operation = useOperationStore((s) => s.operation)
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const [sessionFaults, setSessionFaults] = useState<Fault[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<string | null>(null)

  useStreamFrame((frames) => {
    const motors = frames.motors.faults?.motors ?? {}
    const next: Fault[] = Object.entries(motors)
      .filter(([, entry]) => entry.hw_error)
      .map(([motor, entry]) => ({
        key: faultKey(motor, entry.hw_error!.flags),
        motor,
        joint: entry.joint,
        info: entry.hw_error!,
        relatched: false,
        source: 'session' as const,
      }))
    setSessionFaults((prev) =>
      prev.length === next.length && prev.every((f, i) => f.key === next[i].key) ? prev : next,
    )
  })

  const opActive = operation !== null && isOperationActive(operation)
  const guidedActive = opActive && operation.kind === 'guided_tension'
  // Which source currently knows: the guided routine watches its own bus;
  // with no routine running the session sweep does. Any other routine holds
  // the bus without reporting latches, so nothing is known meanwhile — and
  // nothing is forgotten either.
  const known = guidedActive || !opActive
  const faults: Fault[] = guidedActive
    ? Object.values((operation.extra as GuidedTensionExtra | null)?.faults ?? {}).map((f) => ({
        key: faultKey(f.motor, f.flags, Boolean(f.relatched)),
        motor: String(f.motor),
        joint: f.joint,
        info: f,
        relatched: Boolean(f.relatched),
        source: 'operation' as const,
      }))
    : known
      ? sessionFaults
      : []

  // A dismissal lasts until whichever source knows reports the fault gone;
  // the same fault coming back later is news again.
  const presentKeys = faults.map((f) => f.key).join('|')
  useEffect(() => {
    if (!known) return
    const present = new Set(faults.map((f) => f.key))
    setDismissed((prev) => {
      const kept = new Set([...prev].filter((k) => present.has(k)))
      return kept.size === prev.size ? prev : kept
    })
  }, [known, presentKeys])

  const shown = faults.find((f) => !dismissed.has(f.key))
  if (!shown) return null

  const rebootInOperation = () => {
    setBusy(shown.key)
    api
      .operationInput(`reboot:${shown.motor}`)
      .catch(fail)
      .finally(() => setBusy(null))
  }

  return (
    <div className="fault-popup" role="alertdialog" aria-label="Motor fault">
      <div className="fault-popup-title">
        Motor {shown.motor} is not holding{shown.relatched ? ' — latched again' : ''}
      </div>
      <div className="fault-popup-headline">{shown.info.headline}</div>
      <div className="fault-popup-advice">
        {shown.info.disabled_note} {shown.info.advice}
        {shown.source === 'session' && torqueOn && ' Torque must be off before the reboot.'}
      </div>
      <div className="fault-popup-actions">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setDismissed((prev) => new Set([...prev, shown.key]))}
        >
          Later
        </button>
        {shown.source === 'operation' ? (
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy === shown.key}
            title="Reboot the motor to clear the latch, then hold it again where it stands."
            onClick={rebootInOperation}
          >
            {busy === shown.key ? '…' : `Reboot motor ${shown.motor}`}
          </button>
        ) : (
          <RebootButton
            id={shown.motor}
            needsCooling={shown.info.needs_cooling}
            label={`Reboot motor ${shown.motor}`}
            className="btn btn-primary"
          />
        )}
      </div>
    </div>
  )
}

// Baud rate for the whole bus.
//
// Bus-wide by necessity, not by choice: a motor switches rate the instant the
// write lands, and a port can only be open at one rate — so changing a single
// motor orphans it from the rest of the chain. Changing all of them and then
// re-scanning is the only version of this that leaves a working bench.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import {
  CORE_WITH_TRANSPORT_BAUDS,
  corePredates,
  updateHint,
} from '../../api/coreVersion'
import { useAppStore } from '../../state/appStore'
import { RegisterPopover } from './RegisterPopover'

export function BusBaudPanel({ onClose }: { onClose: () => void }) {
  const setError = useAppStore((s) => s.setError)
  const core = useAppStore((s) => s.handInfo?.core)
  const [motorCount, setMotorCount] = useState(0)
  const [rates, setRates] = useState<number[]>([])
  const [current, setCurrent] = useState<number | null>(null)
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  const fail = useCallback(
    (e: unknown) => setError(String((e as Error).message ?? e)),
    [setError],
  )

  useEffect(() => {
    void api
      .busBaud()
      .then((r) => {
        setRates(r.rates)
        setCurrent(r.current)
        setLoaded(true)
      })
      .catch(fail)
    void api
      .motorsDirect()
      .then((r) => setMotorCount((r.motors ?? []).length))
      .catch(fail)
  }, [fail])

  // No rates with a loaded panel means the core could not be asked what the
  // transport carries. A development checkout carries whatever version it was
  // cut from, so its number says nothing about what it contains.
  const coreTooOld =
    loaded && rates.length === 0 && corePredates(core, CORE_WITH_TRANSPORT_BAUDS)

  const apply = () => {
    const rate = parseInt(choice, 10)
    if (!Number.isFinite(rate)) return
    if (
      !window.confirm(
        `Change ALL ${motorCount} motors on this bus to ${rate.toLocaleString()} baud?\n\n` +
          'Every motor is rewritten at the current rate first, then the host ' +
          'follows the bus to the new one. A motor that does not take the ' +
          'change is left behind at the old rate and will not answer until it ' +
          'is set back — which needs a host that can still reach it.',
      )
    )
      return
    setBusy(true)
    void api
      .setBusBaud(rate)
      .then((r) => {
        setOutcome(
          r.failed.length === 0
            ? `all ${r.changed.length} motors now at ${r.requested.toLocaleString()}`
            : `${r.changed.length} changed, ${r.failed.length} did not: ` +
              `motors ${r.failed.join(', ')} are still at the old rate`,
        )
        setCurrent(r.requested)
        setError(null)
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }

  return (
    <RegisterPopover
      title="Bus baud rate"
      warning={
        'Applies to every motor on the bus. One motor cannot be changed on ' +
        'its own: the port carries a single rate, so a lone change would ' +
        'orphan that motor from the rest.'
      }
      width={380}
      onClose={onClose}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ color: 'var(--dim)' }}>
          now {current === null ? '--' : current.toLocaleString()}
        </span>
        <select
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          style={{ fontSize: 11 }}
        >
          <option value="">change to…</option>
          {rates.map((rate) => (
            <option key={rate} value={rate}>
              {rate.toLocaleString()}
            </option>
          ))}
        </select>
        <button
          className="btn btn-danger"
          disabled={choice === '' || busy || motorCount === 0}
          onClick={apply}
        >
          {busy ? 'changing…' : `change all ${motorCount}`}
        </button>
      </div>
      {coreTooOld && (
        <div style={{ marginTop: 6, fontSize: 10, color: 'var(--dimmer)' }}>
          <span style={{ color: 'var(--warn)' }}>
            orca_core {core?.version} cannot report which rates the board
            between these motors and this computer will carry.
          </span>{' '}
          {CORE_WITH_TRANSPORT_BAUDS} can. Until then no rate is offered,
          because a rate the board will not follow moves every motor somewhere
          nothing on this port can reach. Update with <code>{updateHint()}</code>{' '}
          and reconnect.
        </div>
      )}
      {outcome && (
        <div style={{ marginTop: 6, color: 'var(--dim)' }}>{outcome}</div>
      )}
    </RegisterPopover>
  )
}

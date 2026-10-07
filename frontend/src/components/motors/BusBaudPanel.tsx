// Baud rate for the whole bus.
//
// Bus-wide by necessity, not by choice: a motor switches rate the instant the
// write lands, and a port can only be open at one rate — so changing a single
// motor orphans it from the rest of the chain. Changing all of them and then
// re-scanning is the only version of this that leaves a working bench.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function BusBaudPanel({ motorCount }: { motorCount: number }) {
  const setError = useAppStore((s) => s.setError)
  const [open, setOpen] = useState(false)
  const [rates, setRates] = useState<number[]>([])
  const [current, setCurrent] = useState<number | null>(null)
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)

  const fail = useCallback(
    (e: unknown) => setError(String((e as Error).message ?? e)),
    [setError],
  )

  useEffect(() => {
    if (!open || rates.length) return
    void api
      .busBaud()
      .then((r) => {
        setRates(r.rates)
        setCurrent(r.current)
      })
      .catch(fail)
  }, [open, rates.length, fail])

  const apply = () => {
    const rate = parseInt(choice, 10)
    if (!Number.isFinite(rate)) return
    if (
      !window.confirm(
        `Change ALL ${motorCount} motors on this bus to ${rate.toLocaleString()} baud?\n\n` +
          'Every motor is rewritten and the bench is re-scanned at the new ' +
          'rate. A motor that does not take the change is left behind at the ' +
          'old rate and will not answer until it is set back.',
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
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      style={{ marginTop: 10, fontSize: 10 }}
    >
      <summary style={{ cursor: 'pointer', color: 'var(--dimmer)' }}>
        Bus baud rate
      </summary>
      <div style={{ padding: '6px 0 0 0' }}>
        <div style={{ color: 'var(--warn)', marginBottom: 6 }}>
          Applies to every motor on the bus. One motor cannot be changed on its
          own: the port carries a single rate, so a lone change would orphan
          that motor from the rest.
        </div>
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
            disabled={choice === '' || busy}
            onClick={apply}
          >
            {busy ? 'changing…' : `change all ${motorCount}`}
          </button>
        </div>
        {outcome && (
          <div style={{ marginTop: 6, color: 'var(--dim)' }}>{outcome}</div>
        )}
      </div>
    </details>
  )
}

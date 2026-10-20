// Fingertip module numbers (tactile hands): the number decides which finger a
// fingertip's data appears as. The connector board renumbers one fingertip; the
// others may stay connected if their numbers differ. The hand is then
// power-cycled and checked.

import { useState } from 'react'
import { api } from '../../api/rest'
import type { Finger, FingertipExtra, FoundFingertip } from '../../api/types'
import { FINGERS } from '../../api/types'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { FlowRunning } from './FlowStep'
import { failToBanner } from './setupUtils'

const KIND = 'number_fingertip'
const SPARE = 5
const TARGETS: [number, Finger | 'spare'][] = [...FINGERS.map((f, i): [number, Finger] => [i, f]), [SPARE, 'spare']]

const fitsText = (tip: FoundFingertip) => tip.fits.map((m) => `${m} ${FINGERS[m]}`).join(', ')
const misfit = (tip: FoundFingertip) => tip.part !== null && tip.module !== SPARE && !tip.fits.includes(tip.module)

export function FingertipNumbering() {
  const operation = useOperationStore((s) => s.operation)
  const [source, setSource] = useState<number | null>(null)
  const [target, setTarget] = useState<number | null>(null)
  const mine = operation?.kind === KIND ? operation : null
  const active = mine && isOperationActive(mine) ? mine : null
  const busy = isOperationActive(operation)
  const extra = (mine?.extra ?? null) as FingertipExtra | null
  const found = extra?.found ?? []
  const taken = new Set(found.map((t) => t.module))
  // A lone fingertip is the one to renumber; picks drop out when a scan contradicts them.
  const from = found.length === 1 ? found[0].module : source !== null && taken.has(source) ? source : null
  const to = target !== null && !taken.has(target) ? target : null
  const collision = extra !== null && (extra.garbled_modules.length > 0 || extra.result === 'bus_error')
  const blocked = collision || (found.length > 1 && extra?.targeted === false)

  const read = () => api.operationStart(KIND, { mode: 'detect' }).catch(failToBanner)
  const set = () =>
    api
      .operationStart(KIND, { mode: 'number', finger: to === SPARE ? 'spare' : FINGERS[to!], current_module: from })
      .catch(failToBanner)
  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null

  return (
    <div className="fingertip-numbering">
      <span className="flow-step-title">Fingertip module number</span>
      <span className="fingertip-hint">Read, pick a fingertip and a free number (5 = spare). Power-cycle when asked.</span>
      {found.length > 0 && (
        <div className="flow-row">
          <span className="fingertip-label">Fingertip</span>
          {found.map((tip) => (
            <button
              key={tip.module}
              className={`finger-chip${tip.module === from ? ' has-selection' : ''}`}
              disabled={active !== null}
              title={tip.part ? `${tip.part}, fits ${fitsText(tip) || 'no finger'}` : undefined}
              onClick={() => setSource(tip.module)}
            >
              {tip.module} {tip.finger}
              {misfit(tip) ? ' ⚠' : ''}
            </button>
          ))}
        </div>
      )}
      <div className="flow-row">
        <span className="fingertip-label">New number</span>
        {TARGETS.map(([m, label]) => (
          <button
            key={m}
            className={`finger-chip${m === to ? ' has-selection' : ''}`}
            disabled={active !== null || taken.has(m)}
            onClick={() => setTarget(m)}
          >
            {m} {label}
          </button>
        ))}
      </div>
      {awaiting ? (
        <div className="fingertip-prompt">
          <span>{awaiting.prompt}</span>
          <div className="flow-row">
            {awaiting.options.map((option, i) => (
              <button
                key={option}
                className={i === 0 ? 'btn btn-primary' : 'btn'}
                onClick={() => void api.operationInput(option).catch(failToBanner)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      ) : active ? (
        <div className="flow-row">
          <FlowRunning phase={active.phase} detail={active.detail} />
          <button
            className="btn"
            disabled={active.state === 'stopping'}
            onClick={() => void api.operationStop().catch(failToBanner)}
          >
            Stop
          </button>
        </div>
      ) : (
        <div className="flow-row">
          <button className="btn" disabled={busy} onClick={() => void read()}>
            Read
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || blocked || from === null || to === null}
            onClick={() => void set()}
          >
            {from !== null && to !== null ? `Set ${from} → ${to}` : 'Set'}
          </button>
        </div>
      )}
      {extra && <FingertipResult extra={extra} from={from} collision={collision} error={mine?.error ?? null} />}
    </div>
  )
}

function FingertipResult({
  extra,
  from,
  collision,
  error,
}: {
  extra: FingertipExtra
  from: number | null
  collision: boolean
  error: string | null
}) {
  const found = extra.found
  const tip = found.find((t) => t.module === from)
  const shared = extra.garbled_modules
  return (
    <div className="fingertip-result">
      {collision ? (
        <span className="flow-info warn">
          ⚠ Two fingertips share {shared.length > 0 ? `module ${shared.join(', ')}` : 'a number'} (or a bad
          cable). Unplug one.
        </span>
      ) : found.length === 0 ? (
        <span>No fingertip answered.</span>
      ) : found.length > 1 && !extra.targeted ? (
        <span className="flow-info warn">⚠ This board&apos;s firmware renumbers only a lone fingertip. Connect only one.</span>
      ) : null}
      {tip && (
        <span>
          Module {tip.module} ({tip.finger}){tip.part ? ` · ${tip.part}` : ''}
          {tip.fits.length > 0 ? ` · fits ${fitsText(tip)}` : ''}
        </span>
      )}
      {extra.verified === true && <span>Set to {extra.target_module} ✓</span>}
      {error && <span className="flow-info warn">⚠ {error}</span>}
    </div>
  )
}

// Warning lines for fingers whose slot reports another finger's fingertip model.
export function FingertipMismatches({
  mismatches,
}: {
  mismatches: Partial<Record<Finger, [string, string]>> | undefined
}) {
  const entries = Object.entries(mismatches ?? {}) as [Finger, [string, string]][]
  if (entries.length === 0) return null
  return (
    <div className="flow-info warn" title="Renumber under Setup › Advanced">
      ⚠ fingertip in the wrong slot:{' '}
      {entries.map(([f, [expected, found]]) => `${f} reports ${found} (expects ${expected})`).join('; ')}
    </div>
  )
}

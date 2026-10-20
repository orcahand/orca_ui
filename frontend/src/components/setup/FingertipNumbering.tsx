// Fingertip module numbers (tactile hands): the number decides which finger a
// fingertip's data appears as. With one fingertip plugged in, the connector
// board renumbers it; the hand is then power-cycled and checked.

import { useState } from 'react'
import { api } from '../../api/rest'
import type { Finger, FingertipExtra } from '../../api/types'
import { FINGERS } from '../../api/types'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { FlowRunning } from './FlowStep'
import { failToBanner } from './setupUtils'

const KIND = 'number_fingertip'

export function FingertipNumbering() {
  const operation = useOperationStore((s) => s.operation)
  const [finger, setFinger] = useState<Finger | null>(null)
  const mine = operation?.kind === KIND ? operation : null
  const active = mine && isOperationActive(mine) ? mine : null
  const busy = isOperationActive(operation)
  const extra = (mine?.extra ?? null) as FingertipExtra | null

  const read = () => api.operationStart(KIND, { mode: 'detect' }).catch(failToBanner)
  const set = () => api.operationStart(KIND, { finger, mode: 'number' }).catch(failToBanner)
  const awaiting = active?.state === 'awaiting_input' ? active.awaiting : null

  return (
    <div className="fingertip-numbering">
      <span className="flow-step-title">Fingertip module number</span>
      <span className="fingertip-hint">One fingertip connected. Power-cycle when asked.</span>
      <div className="flow-row">
        {FINGERS.map((f, i) => (
          <button
            key={f}
            className={`finger-chip${f === finger ? ' has-selection' : ''}`}
            disabled={active !== null}
            onClick={() => setFinger(f)}
          >
            {i} {f}
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
          <button className="btn btn-primary" disabled={busy || finger === null} onClick={() => void set()}>
            {finger === null ? 'Set' : `Set to ${FINGERS.indexOf(finger)}`}
          </button>
        </div>
      )}
      {extra && <FingertipResult extra={extra} error={mine?.error ?? null} />}
    </div>
  )
}

function FingertipResult({ extra, error }: { extra: FingertipExtra; error: string | null }) {
  const found = extra.found_modules
  const current = extra.found_finger ? ` (currently ${extra.found_finger})` : ''
  // Two fingertips on one number answer over each other: the board sees a garbled reply.
  const several = found.length > 1 || extra.result === 'bus_error'
  return (
    <div className="fingertip-result">
      {several ? (
        <span className="flow-info warn">
          ⚠ Several fingertips connected
          {found.length > 1 ? ` (modules ${found.join(', ')})` : ' (or a bad cable)'}. Connect only one.
        </span>
      ) : (
        <span>
          {found.length === 0
            ? 'No fingertip answered.'
            : `Found module ${found[0]}${current}${extra.part ? ` · ${extra.part}` : ''}`}
        </span>
      )}
      {found.length === 1 && extra.fits.length > 0 && (
        <span>Fits {extra.fits.map(([m, f]) => `${m} ${f}`).join(', ')}</span>
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

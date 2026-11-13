// What the console knows about the connected physical hand from its own folder
// in orca_core's hand store: who it is (serial, else board ID) and its
// nickname, when its calibration was taken, and whose joint ranges it runs on.
// Shown in the header's hand menu and in Setup's Calibrate step.

import { useState } from 'react'
import { api } from '../../api/rest'
import type { HandStoreInfo } from '../../api/types'
import { useOperationActive } from '../../state/operationStore'
import { calendarDate, handFailed, refreshHandInfo } from './handStore'

function NicknameField({ hand }: { hand: HandStoreInfo }) {
  const [draft, setDraft] = useState<string | null>(null)
  const save = () => {
    if (draft === null) return
    const value = draft.trim() || null
    setDraft(null)
    if (value === (hand.nickname ?? null)) return
    api
      .setHandNickname(value)
      .then(() => refreshHandInfo())
      .catch(handFailed('save the nickname'))
  }
  if (draft !== null) {
    return (
      <input
        className="hand-nickname-input"
        autoFocus
        maxLength={40}
        value={draft}
        placeholder="nickname"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') setDraft(null)
        }}
      />
    )
  }
  return (
    <button
      className="hand-link"
      title="A name for this hand, shown only in this console"
      onClick={() => setDraft(hand.nickname ?? '')}
    >
      {hand.nickname ? `“${hand.nickname}” · rename` : 'add a nickname'}
    </button>
  )
}

function RestorePrevious({ hand }: { hand: HandStoreInfo }) {
  const busy = useOperationActive()
  const [asking, setAsking] = useState(false)
  const [working, setWorking] = useState(false)
  const { previous_at: previousAt } = hand.calibration
  if (!hand.calibration.previous_available) return null
  const restore = () => {
    setWorking(true)
    api
      .restorePreviousCalibration()
      .then(() => refreshHandInfo())
      .catch(handFailed('restore the previous calibration'))
      .finally(() => {
        setWorking(false)
        setAsking(false)
      })
  }
  if (asking) {
    return (
      <span className="hand-confirm">
        put back the calibration{previousAt ? ` from ${calendarDate(previousAt)}` : ''}? The hand
        reconnects.
        <button className="hand-link" disabled={working || busy} onClick={restore}>
          restore
        </button>
        <button className="hand-link" onClick={() => setAsking(false)}>
          cancel
        </button>
      </span>
    )
  }
  return (
    <button
      className="hand-link"
      disabled={busy}
      title={busy ? 'An operation is running — stop it first.' : undefined}
      onClick={() => setAsking(true)}
    >
      restore previous calibration
    </button>
  )
}

export function HandDetails({ hand }: { hand: HandStoreInfo }) {
  const { calibration, joint_ranges: ranges } = hand
  return (
    <div className="hand-details">
      <div className="hand-line">
        <span className="hand-key">hand</span>
        <code title="Serial, else board ID: the hand's folder in the hand store">{hand.id}</code>
        <NicknameField hand={hand} />
      </div>
      <div className="hand-line">
        <span className="hand-key">calibration</span>
        <span title={calibration.path ?? undefined}>
          {calibration.calibrated_at
            ? `calibrated ${calendarDate(calibration.calibrated_at)}`
            : 'none on this computer yet'}
        </span>
        <RestorePrevious hand={hand} />
      </div>
      <div className="hand-line">
        <span className="hand-key">joint ranges</span>
        <span>
          {ranges.source === 'measured'
            ? `measured on this hand${ranges.measured_at ? ` (${calendarDate(ranges.measured_at)})` : ''}`
            : 'model defaults'}
        </span>
      </div>
    </div>
  )
}

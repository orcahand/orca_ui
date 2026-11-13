// Notices about the connected hand's files, as banners that never block:
// the board holding a newer calibration than this computer, and per-hand files
// from before the hand store that were found and are not used.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { useOperationActive } from '../../state/operationStore'
import { handFailed, refreshHandInfo } from '../hand/handStore'
import { shortDate } from '../setup/setupUtils'

function BoardCalibrationNotice() {
  const newer = useAppStore((s) => s.handInfo?.hand?.board_calibration_newer ?? null)
  const busy = useOperationActive()
  const [working, setWorking] = useState(false)
  if (!newer) return null
  const answer = (choice: 'use_board' | 'keep_session' | 'keep_until_change') => {
    setWorking(true)
    api
      .boardCalibration(choice)
      .then(() => refreshHandInfo())
      .catch(handFailed(choice === 'use_board' ? "take the board's calibration" : "keep this computer's calibration"))
      .finally(() => setWorking(false))
  }
  const board = shortDate(newer.board.calibrated_at)
  const computer = shortDate(newer.computer.calibrated_at)
  return (
    <div className="hand-notice">
      <span>
        The board's calibration{board ? ` (${board})` : ''} is newer than this computer's
        {computer ? ` (${computer})` : ''}.
      </span>
      <button
        className="btn btn-secondary btn-sm"
        disabled={working || busy}
        title={busy ? 'An operation is running — stop it first.' : 'The hand reconnects on it.'}
        onClick={() => answer('use_board')}
      >
        use it
      </button>
      <button
        className="btn btn-secondary btn-sm"
        disabled={working}
        title="Hidden until the hand next connects."
        onClick={() => answer('keep_session')}
      >
        keep this computer's
      </button>
      <button
        className="hand-link"
        disabled={working}
        title="Asks again once the board's or this computer's calibration changes."
        onClick={() => answer('keep_until_change')}
      >
        don't ask again until a calibration changes
      </button>
    </div>
  )
}

function LegacyFilesNotice() {
  const files = useAppStore((s) => s.handInfo?.hand?.legacy_files) ?? []
  const calibrated = useAppStore((s) => Boolean(s.handInfo?.hand?.calibration.calibrated_at))
  if (files.length === 0) return null
  const dismiss = () =>
    void api
      .dismissLegacyFiles()
      .then(() => refreshHandInfo())
      .catch(handFailed('dismiss the notice'))
  return (
    <div className="hand-notice">
      <span title={files.join('\n')}>
        Older calibration and setup files from before this version were found and aren't used
        {calibrated ? '.' : '; please calibrate.'}
      </span>
      <button className="btn btn-secondary btn-sm" onClick={dismiss}>
        Dismiss
      </button>
    </div>
  )
}

export function HandNotices() {
  return (
    <>
      <BoardCalibrationNotice />
      <LegacyFilesNotice />
    </>
  )
}

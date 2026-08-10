// Stands in for the EncoderPanel when the hand declares joint encoders but
// connected without them. Without this the panel just vanishes from the
// dashboard, which reads as a layout bug rather than a hand that needs
// attention.
//
// Two different faults land here and they have different fixes: an
// uncalibrated hand (the loop refuses to close on joints with no reference)
// and encoders that failed to come up at connect. Only the first is fixed by
// calibrating — offering that button for the second sends people to run a
// full hardstop sweep that cannot change the outcome.

import { useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'

export function EncoderUnavailableCard() {
  const calibration = useAppStore((s) => s.handInfo?.calibration ?? null)
  const setView = useAppStore((s) => s.setView)
  const setError = useAppStore((s) => s.setError)
  const [reconnecting, setReconnecting] = useState(false)

  const needsCalibration = calibration?.needs_calibration === true

  const reconnect = async () => {
    setReconnecting(true)
    try {
      await api.reconnect()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setReconnecting(false)
    }
  }

  return (
    <Panel title="Joint Encoders">
      <div className="detecting-card">
        <div className="big">JOINT SENSING UNAVAILABLE</div>
        {needsCalibration ? (
          <>
            <div>{calibration?.hint}</div>
            <div style={{ marginTop: 16 }}>
              <button
                className="btn btn-primary"
                onClick={() => setView('setup')}
              >
                Calibrate the hand
              </button>
            </div>
          </>
        ) : (
          <>
            <div>
              the hand is calibrated, so calibrating again will not help — the
              encoder stream did not come up when the hand connected, and the
              console has been running without it since. Reconnect to try the
              feedback tier again; if it keeps dropping, check the encoder board
              and its cable. The reason for each failed attempt is printed by
              the backend as a “connect tier … failed” warning.
            </div>
            <div style={{ marginTop: 16 }}>
              <button
                className="btn btn-secondary"
                disabled={reconnecting}
                onClick={() => void reconnect()}
              >
                {reconnecting ? 'Reconnecting…' : 'Reconnect'}
              </button>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}

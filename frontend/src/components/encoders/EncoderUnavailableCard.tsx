// Stands in for the EncoderPanel when the hand declares joint encoders but
// connected without them. Without this the panel just vanishes from the
// dashboard, which reads as a layout bug rather than a hand that needs
// calibrating.

import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'

export function EncoderUnavailableCard() {
  const calibration = useAppStore((s) => s.handInfo?.calibration ?? null)
  const setView = useAppStore((s) => s.setView)

  return (
    <Panel title="Joint Encoders">
      <div className="detecting-card">
        <div className="big">JOINT SENSING UNAVAILABLE</div>
        <div>
          {calibration?.hint ??
            'the joint feedback loop could not start, so measured joint ' +
              'angles are unavailable'}
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary" onClick={() => setView('setup')}>
            Calibrate the hand
          </button>
        </div>
      </div>
    </Panel>
  )
}

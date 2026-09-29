// Motors tab: link status (capability badges + stream Hz meters + reconnect),
// per-motor health, control-loop tuning/diagnostics, and the event log —
// everything relocated off the daily-driver dashboard and header.

import { TOPICS } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { LinkActions } from '../common/LinkActions'
import { Panel } from '../common/Panel'
import { EventLog } from '../motors/EventLog'
import { LoopStatsBar } from '../motors/LoopStatsBar'
import { MotorChainPanel } from '../motors/MotorChainPanel'
import { MotorHealthPanel } from '../motors/MotorHealthPanel'
import { ServoTuningPanel } from '../motors/ServoTuningPanel'
import { TuningPanel } from '../motors/TuningPanel'

export function MotorsView() {
  const status = useAppStore((s) => s.status)
  const rates = useAppStore((s) => s.rates)

  const caps = status?.capabilities
  const measuredHz = rates[TOPICS.jointsMeasured] ?? 0
  const taxelHz = rates[TOPICS.tactileTaxels] ?? 0

  return (
    <>
      <Panel title="Link Status" toolbar={<LinkActions />}>
        <div
          style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
        >
          {caps ? (
            <>
              <span className={`capability-badge ${caps.motors ? 'on' : ''}`}>
                MOTORS
              </span>
              <span className={`capability-badge ${caps.tactile ? 'on' : ''}`}>
                TACTILE
              </span>
              <span className={`capability-badge ${caps.encoders ? 'on' : ''}`}>
                ENCODERS
              </span>
              {caps.degraded && (
                <span className="capability-badge warn">DEGRADED</span>
              )}
            </>
          ) : (
            <span style={{ fontSize: 10, color: 'var(--dimmer)' }}>
              no session — capabilities appear once the hand connects
            </span>
          )}
          <span className="rate-meters">
            {measuredHz > 0 && `joints ${measuredHz}Hz`}
            {measuredHz > 0 && taxelHz > 0 && ' · '}
            {taxelHz > 0 && `taxels ${taxelHz}Hz`}
          </span>
        </div>
      </Panel>
      <MotorHealthPanel />
      <ServoTuningPanel />
      {caps?.feedback_loop && (
        <Panel title="Control Loop">
          <TuningPanel />
          <LoopStatsBar />
        </Panel>
      )}
      <MotorChainPanel />
      <EventLog />
    </>
  )
}

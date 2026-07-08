// Supervisor/operation event log: status transitions, backend errors, and
// operation terminals accumulated client-side (bounded, newest first).

import { useEventLogStore } from '../../state/eventLogStore'
import { Panel } from '../common/Panel'

const KIND_COLOR: Record<string, string> = {
  status: 'var(--accent)',
  error: 'var(--err)',
  operation: 'var(--purple)',
}

export function EventLog() {
  const events = useEventLogStore((s) => s.events)
  const clear = useEventLogStore((s) => s.clear)

  const toolbar = (
    <button
      className="btn btn-secondary"
      disabled={events.length === 0}
      onClick={clear}
    >
      Clear
    </button>
  )

  return (
    <Panel title="Event Log" toolbar={toolbar}>
      {events.length === 0 ? (
        <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
          no events yet — status transitions, errors, and operation results
          land here
        </div>
      ) : (
        <div className="event-log">
          {events
            .slice()
            .reverse()
            .map((event) => (
              <div key={event.id} className="event-log-line">
                <span className="event-time">
                  {new Date(event.t).toLocaleTimeString()}
                </span>
                <span
                  className="event-kind"
                  style={{ color: KIND_COLOR[event.kind] }}
                >
                  {event.kind}
                </span>
                <span className="event-text">{event.text}</span>
              </div>
            ))}
        </div>
      )}
    </Panel>
  )
}

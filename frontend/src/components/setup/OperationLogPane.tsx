// Live operation log: the seq-merged cumulative buffer from operationStore.
// Auto-scrolls to the newest line unless the user has scrolled up.

import { useEffect, useRef } from 'react'
import { useOperationStore } from '../../state/operationStore'
import { Panel } from '../common/Panel'

const STICK_THRESHOLD_PX = 24

export function OperationLogPane() {
  const lines = useOperationStore((s) => s.logLines)
  const paneRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  const onScroll = () => {
    const pane = paneRef.current
    if (!pane) return
    stickToBottom.current =
      pane.scrollHeight - pane.scrollTop - pane.clientHeight <
      STICK_THRESHOLD_PX
  }

  useEffect(() => {
    const pane = paneRef.current
    if (pane && stickToBottom.current) pane.scrollTop = pane.scrollHeight
  }, [lines])

  return (
    <Panel title="Operation Log">
      {lines.length === 0 ? (
        <div className="panel-empty">
          no operation output yet — tension, calibrate, and wizard progress
          streams here
        </div>
      ) : (
        <div className="op-log" ref={paneRef} onScroll={onScroll}>
          {lines.map((line) => (
            <div key={line.seq} className="op-log-line">
              <span className="op-log-time">
                {new Date(line.t * 1000).toLocaleTimeString()}
              </span>
              <span className="op-log-text">{line.line}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

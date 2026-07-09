// Annotated camera frames from the streamer child (teleop.preview topic,
// base64 JPEG ≤10 Hz). Bandwidth is opt-in twice over: the WS subscription
// only exists while this panel wants frames, and the child only encodes
// frames while config.preview is true. The <img> is updated outside React
// state (streamStore slot + rAF); the skeleton overlay is green when the
// orientation gate passes and gray when it's rejecting the pose.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import { subscribeTopic, unsubscribeTopic } from '../../api/streamClient'
import { TOPICS } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'
import { Panel } from '../common/Panel'
import { TrackingDot } from './SessionCard'

const CAMERA_SOURCES = new Set(['mediapipe'])

export function CameraPreview() {
  const session = useTeleopStore((s) => s.session)
  const [enabled, setEnabled] = useState(true)
  const [hasFrame, setHasFrame] = useState(false)
  const imgRef = useRef<HTMLImageElement>(null)
  const lastSeq = useRef<number | null>(null)

  const show =
    isTeleopActive(session) &&
    session?.source != null &&
    CAMERA_SOURCES.has(session.source)
  const streaming = show && enabled
  const sessionId = session?.session_id ?? null

  useEffect(() => {
    // fresh session: forget the previous session's frames
    lastSeq.current = null
    setHasFrame(false)
  }, [sessionId])

  useEffect(() => {
    if (!streaming) return
    subscribeTopic(TOPICS.teleopPreview)
    void api.teleopConfig({ preview: true }).catch(() => undefined)
    return () => {
      unsubscribeTopic(TOPICS.teleopPreview)
      void api.teleopConfig({ preview: false }).catch(() => undefined)
    }
  }, [streaming])

  useStreamFrame((frames) => {
    const preview = frames.teleop.preview
    if (!preview || !imgRef.current) return
    if (preview.seq !== null && preview.seq === lastSeq.current) return
    lastSeq.current = preview.seq
    imgRef.current.src = `data:image/jpeg;base64,${preview.jpeg}`
    setHasFrame(true) // no-op re-render once true (Object.is bailout)
  })

  if (!show || !session) return null

  return (
    <Panel
      title="Camera"
      toolbar={
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <TrackingDot session={session} />
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            live preview
          </label>
        </div>
      }
    >
      {enabled ? (
        <div className="teleop-preview-stage">
          <img
            ref={imgRef}
            className="teleop-preview-img"
            style={hasFrame ? undefined : { display: 'none' }}
            alt="camera preview with hand landmarks"
          />
          {!hasFrame && (
            <div className="teleop-preview-waiting">
              waiting for camera frames… if this persists, the camera may be
              in use elsewhere or macOS hasn't granted camera access to the
              terminal that launched orca-ui
            </div>
          )}
        </div>
      ) : (
        <p className="setup-card-hint">
          preview off — tracking state still shows in the session card
        </p>
      )}
    </Panel>
  )
}

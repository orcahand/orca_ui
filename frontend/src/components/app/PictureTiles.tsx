// The app's pictures (app.frames: the latest JPEG per stream, ≤10 Hz), one
// tile per stream: Teleop's camera with the tracked hand drawn in, RL's
// simulation. The topic is subscribed only while this is on screen, and the
// images update outside React state. A tile says "stale" when its stream has
// sent nothing new for a second.

import { useEffect, useRef, useState } from 'react'
import { subscribeTopic, unsubscribeTopic } from '../../api/streamClient'
import { TOPICS } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { Panel } from '../common/Panel'

const STALE_MS = 1000

export function PictureTiles({ sessionId }: { sessionId: string }) {
  const [streams, setStreams] = useState<string[]>([])

  useEffect(() => {
    subscribeTopic(TOPICS.appFrames)
    return () => unsubscribeTopic(TOPICS.appFrames)
  }, [])

  useEffect(() => setStreams([]), [sessionId])

  useStreamFrame((frames) => {
    const names = Object.keys(frames.app.frames).sort()
    setStreams((current) =>
      current.join('\n') === names.join('\n') ? current : names,
    )
  })

  if (streams.length === 0) {
    return (
      <Panel title="Pictures">
        <p className="setup-card-hint">No pictures from the app yet.</p>
      </Panel>
    )
  }
  return (
    <div className="app-pictures">
      {streams.map((name) => (
        <PictureTile key={`${sessionId}/${name}`} name={name} />
      ))}
    </div>
  )
}

function PictureTile({ name }: { name: string }) {
  const imgRef = useRef<HTMLImageElement>(null)
  const lastSeq = useRef<number | null>(null)
  const lastChange = useRef(0)
  const [stale, setStale] = useState(false)

  useStreamFrame((frames) => {
    const frame = frames.app.frames[name]
    if (!frame || !imgRef.current || frame.seq === lastSeq.current) return
    lastSeq.current = frame.seq
    lastChange.current = performance.now()
    imgRef.current.src = `data:image/jpeg;base64,${frame.jpeg}`
    setStale(false)
  })

  useEffect(() => {
    const timer = setInterval(
      () => setStale(performance.now() - lastChange.current > STALE_MS),
      250,
    )
    return () => clearInterval(timer)
  }, [])

  return (
    <Panel
      title={name}
      toolbar={stale ? <span className="app-stale">stale</span> : undefined}
    >
      <div className="app-picture-stage">
        <img ref={imgRef} className="app-picture-img" alt={`${name} picture`} />
      </div>
    </Panel>
  )
}

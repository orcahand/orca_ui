import { useEffect, useState } from 'react'
import { mediaImage } from './media'
import { KNOT_CUES as cues } from './knotSteps'

export function KnotLesson() {
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => {
      if (frame === 10) setPlaying(false)
      else setFrame(frame + 1)
    }, 2100)
    return () => clearTimeout(timer)
  }, [playing, frame])
  function select(i: number) {
    setPlaying(false)
    setFrame(i)
  }
  return (
    <section className="assembly-knot" aria-label="Ashley stopper visual lesson">
      <div className="assembly-row">
        <div></div>
        <span>{frame + 1} / 11</span>
      </div>
      <div className="assembly-knot-layout">
        <img
          {...mediaImage(`./assembly/media/ashley-${frame + 1}.jpg`)}
          alt={`Ashley stopper, stage ${frame + 1}: ${cues[frame]}`}
        />
        <div>
          <div className="assembly-media-controls">
            <button disabled={frame === 0} onClick={() => select(frame - 1)}>
              ← Back
            </button>
            <button
              onClick={() => {
                if (frame === 10) setFrame(0)
                setPlaying(!playing)
              }}
            >
              {playing ? 'Pause' : 'Play sequence'}
            </button>
            <button disabled={frame === 10} onClick={() => select(frame + 1)}>
              Next →
            </button>
          </div>
        </div>
      </div>
      <div className="assembly-knot-frames">
        {cues.map((cue, i) => (
          <button
            key={i}
            aria-label={`Knot stage ${i + 1}`}
            title={cue}
            aria-pressed={i === frame}
            onClick={() => select(i)}
          >
            <img {...mediaImage(`./assembly/media/ashley-${i + 1}.jpg`)} alt="" />
            <span>{i + 1}</span>
          </button>
        ))}
      </div>
    </section>
  )
}

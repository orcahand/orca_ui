import {GuideText} from './GuideEditing'
import { useEffect, useState } from 'react'
const cues = [
  'Leave a working end long enough to handle. Fold the cord back to make a bight.',
  'Fold the bight to form two loops. Keep track of which side leads to the long standing part.',
  'Pass the loop on the standing-part side through the other loop.',
  'Keep the new loop open. Bring the short working end toward it.',
  'Feed the working end through the open loop.',
  'Begin snugging the half knot while keeping the working end through the loop.',
  'Snug the half knot completely before tightening the rest.',
  'Pull the short working end to remove its slack.',
  'Pull the long standing part to finish tightening.',
  'Dress the knot: arrange the turns neatly, then pull firmly to set it.',
  'Inspect the underside. Look for three distinct lobes around the standing part.',
]
export function KnotLesson() {
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => { if (frame === 10) setPlaying(false); else setFrame(frame+1) }, 2100)
    return () => clearTimeout(timer)
  }, [playing,frame])
  function select(i:number) { setPlaying(false); setFrame(i) }
  return <section className="assembly-knot" aria-label="Ashley stopper visual lesson">
    <div className="assembly-row"><div><span className="assembly-eyebrow">ONE KNOT (FRAME BY FRAME)</span><h3><GuideText variant field="prose/KnotLesson.tsx/188ef63243" text={"Follow the cord"} label="Section heading"/></h3></div><span>{frame+1} / 11</span></div>
    <div className="assembly-knot-layout"><img src={`./assembly/media/ashley-${frame+1}.jpg`} alt={`Ashley stopper, stage ${frame+1}: ${cues[frame]}`} /><div><span className="assembly-eyebrow">{frame === 10 ? 'CHECK THE FINISHED KNOT' : 'YOUR NEXT MOVEMENT'}</span><p aria-live={playing ? 'off' : 'polite'}><GuideText variant field="prose/KnotLesson.tsx/4e77151b84" text={String(cues[frame])} label="Guide text"/></p><p className="assembly-muted"><GuideText variant field="prose/KnotLesson.tsx/3737e55ec2" text={["Standing part = long end.","\n","Working end = short end you pass through."].join('').trim()} label="Guide text"/></p><div className="assembly-media-controls"><button disabled={frame === 0} onClick={() => select(frame-1)}>← Back</button><button onClick={() => {if(frame === 10) setFrame(0); setPlaying(!playing)}}>{playing ? 'Pause' : 'Play sequence'}</button><button disabled={frame === 10} onClick={() => select(frame+1)}>Next →</button></div></div></div>
    <div className="assembly-knot-frames">{cues.map((cue,i) => <button key={i} aria-label={`Knot stage ${i+1}`} title={cue} aria-pressed={i === frame} onClick={() => select(i)}><img src={`./assembly/media/ashley-${i+1}.jpg`} alt="" /><span>{i+1}</span></button>)}</div>
  </section>
}

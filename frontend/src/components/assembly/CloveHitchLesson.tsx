import {GuideText} from './GuideEditing'
import {useEffect,useId,useState} from 'react'

const stages=[
 {crop:'4 4 126 166',cue:'Pass the copper wire around the cable once. Leave a short tail and keep the long working end free for wrapping.'},
 {crop:'135 4 145 166',cue:'Cross the working end over the first turn, then take it around the cable again.'},
 {crop:'285 4 125 166',cue:'Bring the working end back to the front. Leave the diagonal crossing loose enough to pass the end underneath.'},
 {crop:'4 178 204 130',cue:'Tuck the working end under the diagonal crossing. Follow the fourth picture carefully: the end passes underneath the crossing wire.'},
 {crop:'214 178 196 130',cue:'Pull the ends gently in opposite directions and snug the two turns against the cable. Keep the long end for the copper wrap; trim the short tail below 2 mm.'},
]
function HitchFrame({frame,thumbnail=false}:{frame:number;thumbnail?:boolean}){
 const clip=useId(),[x,y,width,height]=stages[frame].crop.split(' ').map(Number)
 return <svg viewBox={stages[frame].crop} preserveAspectRatio="xMidYMid meet" role={thumbnail?undefined:'img'} aria-hidden={thumbnail||undefined} aria-label={thumbnail?undefined:`Clove hitch, stage ${frame+1}: ${stages[frame].cue}`}>
  <defs><clipPath id={clip}><rect x={x} y={y} width={width} height={height}/></clipPath></defs>
  <image href="./assembly/touch/clove-hitch.png" width="414" height="312" clipPath={`url(#${clip})`}/>
 </svg>
}
export function CloveHitchLesson(){
 const [frame,setFrame]=useState(0),[playing,setPlaying]=useState(false)
 useEffect(()=>{
  if(!playing)return
  const timer=window.setTimeout(()=>{if(frame===stages.length-1)setPlaying(false);else setFrame(frame+1)},2600)
  return()=>window.clearTimeout(timer)
 },[frame,playing])
 const select=(i:number)=>{setPlaying(false);setFrame(i)}
 return <section className="assembly-knot assembly-clove-hitch" aria-label="Clove hitch visual lesson">
  <div className="assembly-row"><div><span className="assembly-eyebrow">ONE KNOT · FRAME BY FRAME</span><h3><GuideText variant field="prose/CloveHitchLesson.tsx/49b23163f0" text={"Tie the clove hitch"} label="Section heading"/></h3></div><span>{frame+1} / {stages.length}</span></div>
  <div className="assembly-knot-layout"><HitchFrame frame={frame}/><div>
   <span className="assembly-eyebrow">{frame===4?'CHECK THE FINISHED HITCH':'YOUR NEXT MOVEMENT'}</span>
   <p aria-live={playing?'off':'polite'}><GuideText variant field="prose/CloveHitchLesson.tsx/72ac0b75d8" text={String(stages[frame].cue)} label="Guide text"/></p>
   <p className="assembly-muted"><GuideText variant field="prose/CloveHitchLesson.tsx/e44613a76a" text={"The blue bar represents the cable; the white cord represents the copper wire. Working end = the end you move around the cable."} label="Guide text"/></p>
   <div className="assembly-media-controls"><button disabled={frame===0} onClick={()=>select(frame-1)}>← Back</button><button onClick={()=>{if(frame===4)setFrame(0);setPlaying(!playing)}}>{playing?'Pause':'Play sequence'}</button><button disabled={frame===4} onClick={()=>select(frame+1)}>Next →</button></div>
  </div></div>
  <div className="assembly-knot-frames">{stages.map((stage,i)=><button key={i} aria-label={`Clove hitch stage ${i+1}`} title={stage.cue} aria-pressed={frame===i} onClick={()=>select(i)}><HitchFrame frame={i} thumbnail/><span>{i+1}</span></button>)}</div>
  <details className="assembly-hitch-reference"><summary>See the copper wire on the cable</summary><img src="./assembly/touch/wrap-start.png" alt="Close-up of the starting copper-wire hitch around the black cable sleeve"/></details>
  <p className="assembly-muted"><GuideText variant field="prose/CloveHitchLesson.tsx/6fd6c2cb99" text={"Use the same hitch to finish the wrap. Check both wire tails are shorter than 2 mm and the cable insulation is intact."} label="Guide text"/></p>
 </section>
}

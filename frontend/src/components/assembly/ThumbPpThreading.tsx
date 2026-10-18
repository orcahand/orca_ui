import {GuideText} from './GuideEditing'
import {useId,useState} from 'react'
import type {Build} from './buildContent'

const phases=[
 ['Feed from the top','Bring the working section out through the cable channel. Keep the tendon unknotted while feeding.'],
 ['Tie outside the part','Tie the two reinforced Ashley stoppers outside the cable channel, near the midpoint and 10 mm apart (±5 mm).'],
 ['Return through the channel','Feed the tendon back through that same cable-channel opening and out of the PP. Pull the stoppers into their seats and tuck the connecting loop inside.'],
]
/** Sequence diagram alongside the selected CAD part; deliberately not a measured internal route. */
export function ThumbPpThreading({build}:{build:Build}){
 const [phase,setPhase]=useState(0),id=useId().replace(/:/g,''),title=phases[phase]
 return <section className="assembly-thumb-threading" aria-label="Thumb PP cable-channel threading">
  <div className="assembly-row"><h3><GuideText variant field="prose/ThumbPpThreading.tsx/e1d96d51a6" text={"Thread first, tie through the cable channel"} label="Section heading"/></h3><span>{phase+1} / 3</span></div>
  <div className="assembly-thumb-threading-views">
   <figure><img src={`./assembly/renders/${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel/thumb-pp-part.webp`} alt={`${build.side} ${build.version} thumb PP without its skin`}/><figcaption><GuideText variant field="prose/ThumbPpThreading.tsx/dec792b85b" text={"Your thumb PP · keep the cable channel accessible"} label="Guide text"/></figcaption></figure>
   <svg viewBox="0 0 620 470" role="img" aria-label={`${title[0]}. ${title[1]} Simplified sequence diagram, not a measured channel route.`}>
    <defs><marker id={id} markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="m0 0 6 3.5-6 3.5" fill="none" stroke="#287881" strokeWidth="1.5"/></marker></defs>
    <path d="M180 100 Q180 75 205 75 H290 Q315 75 315 100 V173 H287 V228 H315 V348 Q315 372 290 372 H205 Q180 372 180 348 Z" fill="#28343e"/>
    <path d="M222 75 V147 Q222 200 287 200 M245 200 V372" stroke="#fff" strokeWidth="17" fill="none"/>
    <g fill="none" stroke="#287881" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
     {phase===0&&<path d="M222 32 V147 Q222 200 287 200 H440" markerEnd={`url(#${id})`}/>}
     {phase===1&&<><path d="M222 32 V147 Q222 200 287 200 H347 M408 200 H470"/><path d="M347 200 C340 172 368 173 360 199 C345 220 338 189 361 196 M385 200 C378 172 406 173 398 199 C383 220 376 189 399 196" strokeWidth="6"/><path d="M348 181 Q356 167 363 183 M386 181 Q394 167 401 183" stroke="#ac783e"/></>}
     {phase===2&&<><path d="M440 200 H287 Q245 200 245 250 V415" markerEnd={`url(#${id})`}/><path d="M222 32 V147 Q222 170 242 182"/><circle cx="244" cy="188" r="7" fill="#287881"/><circle cx="258" cy="205" r="7" fill="#287881"/></>}
    </g>
    <g fontSize="19" fill="currentColor"><text x="175" y="24">Top entry</text><text x="335" y="145">Cable channel</text><text x="190" y="453">PP outlet</text><text x="340" y="270">{phase===0?'Feed out →':phase===1?'Tie outside':'← Feed back in'}</text></g>
    <path d="M338 152 313 184" stroke="currentColor" fill="none"/>
   </svg>
  </div>
  <p aria-live="polite"><GuideText variant field="prose/ThumbPpThreading.tsx/72a29cc7d8" text={[String(title[0]),"."," ",String(title[1])].join('').trim()} label="Guide text"/></p>
  <div className="assembly-row"><small className="assembly-muted"><GuideText variant field="prose/ThumbPpThreading.tsx/8b46f203dd" text={"The diagram shows the sequence; use the cable channel on your part."} label="Guide text"/></small><div><button className="assembly-secondary" disabled={phase===0} onClick={()=>setPhase(phase-1)} aria-label="Previous threading phase">←</button><button className="assembly-secondary" disabled={phase===2} onClick={()=>setPhase(phase+1)} aria-label="Next threading phase">→</button></div></div>
 </section>
}

import { useEffect, useState } from 'react'
export function TendonPreparation() {
  return <section className="assembly-tendon-preparation" aria-label="Double-knot tendon measurements">
    <svg viewBox="0 0 900 260" role="img" aria-label="2 metre tendon with two reinforced stoppers near its midpoint, 10 millimetres apart plus or minus 5 millimetres">
      <defs><marker id="measure-arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto-start-reverse"><path d="M6 0 0 3 6 6" fill="none" stroke="currentColor"/></marker></defs>
      <path d="M60 145 H840" stroke="#2b818a" strokeWidth="4"/>
      {[415,485].map(x=><g key={x} transform={`translate(${x} 145)`}><path d="M-9 2 C-19 -17 13 -20 9 -1 C-6 21 -20 3 9 -2 C22 -12 8 -27 -7 -11" fill="none" stroke="#2b818a" strokeWidth="5"/><path d="M-9 -13 Q0 -27 10 -12" stroke="#ac783e" strokeWidth="4" fill="none"/></g>)}
      <path d="M60 75 V100 M840 75 V100 M65 85 H835" fill="none" stroke="currentColor" markerStart="url(#measure-arrow)" markerEnd="url(#measure-arrow)"/>
      <text x="450" y="62" textAnchor="middle">2 m total · near the midpoint</text>
      <path d="M415 175 V207 M485 175 V207 M420 195 H480" stroke="currentColor" fill="none" markerStart="url(#measure-arrow)" markerEnd="url(#measure-arrow)"/>
      <text x="450" y="235" textAnchor="middle">10 mm ±5 mm between the two stoppers</text>
    </svg>
    <div className="assembly-anatomy-terms"><p><strong>10 lengths in total</strong><br/>2 per finger, including the thumb: one for DP and one for PP.</p><p><strong>At each anchor</strong><br/>1 Ashley stopper + 1 ordinary single knot on top, tied around the stopper.</p></div>
  </section>
}
export function KnotConventions() {
  return <section className="assembly-knot-conventions"><h3>Anchor knots throughout the build</h3><dl><div><dt>Thumb ABD / AP and CMC / TP</dt><dd>1 Ashley stopper + 3 single knots on top.</dd></div><div><dt>All other joint anchors</dt><dd>1 Ashley stopper + 1 single knot on top.</dd></div><div><dt>Spools</dt><dd>1 Ashley stopper with 3 tendon turns. If a tendon is too short for 3 turns, use Ashley + 2 single knots on top as the fallback.</dd></div></dl><p>Tie each extra single knot around the Ashley stopper, not beside it. The reinforcement belongs to the anchor, not to the free section of tendon.</p></section>
}
export function KnotReinforcement({count}:{count:1|3}) {
  const [phase,setPhase]=useState(0),[playing,setPlaying]=useState(false)
  const labels=['Set the Ashley stopper','Tie a single knot on top','Pull the single knot tight']
  useEffect(()=>{if(!playing)return;const timer=setTimeout(()=>{if(phase===2)setPlaying(false);else setPhase(phase+1)},2200);return()=>clearTimeout(timer)},[phase,playing])
  return <section className="assembly-knot-reinforcement" aria-label={`One Ashley stopper plus ${count} single knots on top`}>
    <div className="assembly-row"><h3>Reinforce the tightened stopper</h3><button className="assembly-secondary" onClick={()=>{if(phase===2)setPhase(0);setPlaying(!playing)}}>{playing?'Pause knot':'Play knot'}</button></div>
    <div className="assembly-motion-phases">{labels.map((label,i)=><button key={label} aria-pressed={phase===i} onClick={()=>{setPhase(i);setPlaying(false)}}><span>{i+1}</span>{label}</button>)}</div>
    <svg viewBox="0 0 700 290" role="img" aria-label={labels[phase]}>
      <defs><linearGradient id="ashley-rope"><stop stopColor="#24636e"/><stop offset=".45" stopColor="#73b5bc"/><stop offset="1" stopColor="#23626d"/></linearGradient><linearGradient id="single-rope"><stop stopColor="#8b541e"/><stop offset=".45" stopColor="#ebbd7a"/><stop offset="1" stopColor="#8b541e"/></linearGradient></defs>
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        <path d="M70 178 H324 M376 178 H625" stroke="url(#ashley-rope)" strokeWidth="9"/>
        <path d="M331 180 C315 174 314 151 332 147 C350 144 361 161 351 178 C342 192 330 197 321 187 C313 177 326 165 347 165 C368 162 384 172 378 185 C372 200 350 193 347 176 C343 156 358 144 372 150 C387 158 375 176 361 181" stroke="#174b53" strokeWidth="14"/>
        <path d="M331 180 C315 174 314 151 332 147 C350 144 361 161 351 178 C342 192 330 197 321 187 C313 177 326 165 347 165 C368 162 384 172 378 185 C372 200 350 193 347 176 C343 156 358 144 372 150 C387 158 375 176 361 181" stroke="url(#ashley-rope)" strokeWidth="10"/>
        <path d="M338 187 Q352 198 369 187" stroke="#174b53" strokeWidth="14"/><path d="M338 187 Q352 198 369 187" stroke="url(#ashley-rope)" strokeWidth="10"/>
        {phase>0&&<g className={phase===2?'assembly-single-tight':'assembly-single-open'}>
          <path d="M315 153 C296 120 319 98 344 112 C373 128 382 111 367 105 C349 97 333 127 355 143 L384 159" stroke="#644019" strokeWidth="12"/>
          <path d="M315 153 C296 120 319 98 344 112 C373 128 382 111 367 105 C349 97 333 127 355 143 L384 159" stroke="url(#single-rope)" strokeWidth="8"/>
          <path d="M334 118 352 130" stroke="#644019" strokeWidth="12"/><path d="M334 118 352 130" stroke="url(#single-rope)" strokeWidth="8"/>
        </g>}
        <path d="M321 190 257 227 H145" stroke="currentColor" strokeWidth="1"/>
        {phase>0&&<path d={phase===1?'M375 110 440 65 H610':'M365 143 440 65 H610'} stroke="#ac783e" strokeWidth="1"/>}
      </g>
      <text x="145" y="251" fontSize="16" fill="currentColor">Tight Ashley stopper</text>
      {phase>0&&<text x="440" y="51" fontSize="16" fill="currentColor">Single overhand knot</text>}
      <text x="350" y="278" textAnchor="middle" fontSize="14" fill="currentColor">{phase===0?'Pull the Ashley firmly before adding reinforcement.':phase===1?'Tie the ordinary single knot around the stopper, on top.':'Pull snug against the Ashley to make one compact anchor.'}</text>
    </svg>
    {count===3&&<p>Repeat the single-knot step twice more: <strong>three single knots in total</strong> on top of the same Ashley stopper.</p>}
  </section>
}

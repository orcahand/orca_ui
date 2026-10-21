import {GuideText} from './GuideEditing'
import { useEffect, useState } from 'react'
import { ASSEMBLY_MOTIONS } from './assemblyMotions'
import { TendonRouting } from './TendonRouting'
import {TENDON_COLORS} from './cadScene'
import {AssemblyComparison} from './AssemblyComparison'
import { PartAssemblyMotion } from './PartAssemblyMotion'
import type { Build } from './buildContent'
import type { AnimationKind } from './guide'

const LESSONS = {
  tube: {title:'Pull the liner through the channel', steps:['Thread the cord','Feed the channel','Pull the liner'], cues:['Pass the free tendon end through the PTFE tube. The stopper knot remains outside the tube, against its end.', 'Feed the free tendon end through the part’s channel until you can grip it on the far side.', 'Pull the free tendon end. The knot bears against the tube and draws it through the channel, instead of pushing the tube from behind.']},
  straight: {title:'Bring the routed joint together', steps:['Check the routing','Draw out slack','Seat the joint'], cues:['Match each tendon to its own channel in the numbered routing photographs above. The model shows the parts you are joining.', 'Draw the tendons straight without changing their order. Look between the parts for trapped or crossed strands.', 'Keep the paths straight while bringing the joint together. Fully seat the bearings, then check that the joint moves freely.']},
  wrist: {title:'Route the two groups in order', steps:['Separate the groups','Palm to dorsal','Dorsal to palmar'], cues:['Identify the palm and dorsum tendon groups at the carpals. Preserve the order within each group.', 'Start with the leftmost palm tendon and the leftmost dorsal wrist channel. Continue in order through the palm group.', 'Route the dorsum group through the palmar wrist channels, preserving its order too. Check individual identities in the next steps.']},
}
export function ThreadingAnimation({kind,build,step}:{kind:AnimationKind;build:Build;step:string}) {
  const [position,setPosition]=useState(0)
  const [channels,setChannels]=useState(true)
  const canSeeThrough=['p33','p42','p46','p54','p62','p64','p68','p89','p123','p126'].includes(step)
  const [tendon,setTendon]=useState(0)
  const [playing,setPlaying]=useState(false)
  const lesson=ASSEMBLY_MOTIONS[step]??LESSONS[kind],phase=step==='p126'?(position<.18?0:position<.65?1:2):Math.min(2,Math.floor(position*3))
  useEffect(()=>{
    if(!playing)return
    let frame=0,previous=0
    const tick=(now:number)=>{if(previous){const elapsed=now-previous;setPosition(p=>Math.min(1,p+elapsed/7000))}previous=now;frame=requestAnimationFrame(tick)}
    frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)
  },[playing])
  useEffect(()=>{if(position>=1)setPlaying(false)},[position])
  const legend=step==='p68'?['AP toward pinky','PP flexion','DP flexion','TP flexion','TP extension','DP extension','PP extension','AP toward thumb'].map((name,i)=>[TENDON_COLORS[i],name]):step==='p62'?[['#d99d54','AP toward thumb'],['#81bb50','PP extension'],['#d3bd50','DP extension'],['#ae86eb','DP flexion'],['#f26962','PP flexion'],['#29bfcb','AP toward pinky'],['#f7faf4','TP anchor ends']]:[['#d5a000','DP flexion'],['#893ee7','DP extension'],['#0098be','PP extension'],['#f17615','PP flexion'],...(['p42','p54'].includes(step)?[['#f7faf4','AP anchor ends']]:[])]
  return <section className="assembly-motion assembly-motion-lesson" data-contrast={['p89','p123','p126'].includes(step)} aria-label={lesson.title}>
    <div className="assembly-row"><div><h3><GuideText variant field="prose/ThreadingAnimation.tsx/d5a24a9a50" text={String(lesson.title)} label="Section heading"/></h3></div><button className="assembly-secondary" aria-label={playing?'Pause animation':'Play animation'} onClick={()=>{if(position>=1)setPosition(0);setPlaying(!playing)}}>{playing?'Ⅱ':'▶'}</button></div>

    <div className={`assembly-joint-and-routing ${['p42','p54','p62','p64'].includes(step)?'':'assembly-joint-only'}`}><div className="assembly-model-controls-frame" data-has-controls={canSeeThrough}>{canSeeThrough&&<label className="assembly-see-through"><input type="checkbox" checked={channels} onChange={e=>setChannels(e.target.checked)}/> See through the parts</label>}<AssemblyComparison step={step} build={build} model={()=><PartAssemblyMotion build={build} step={step} position={position} tendon={tendon} channels={channels}/>}><PartAssemblyMotion build={build} step={step} position={position} tendon={tendon} channels={channels}/></AssemblyComparison></div><TendonRouting compact build={build} step={step} selectedTendon={tendon} onTendon={setTendon}/></div>
    {['p33','p46','p68'].includes(step)&&<div className="assembly-tendon-legend" aria-label="Tendon color legend">{legend.map(([color,label],i)=>step==='p68'?<button key={label} aria-pressed={tendon===i} onClick={()=>setTendon(i)}><i style={{background:color}}/>{label}</button>:<span key={label}><i style={{background:color}}/>{label}</span>)}</div>}
    {step==='p68'&&<p className="assembly-muted"><GuideText variant field="prose/ThreadingAnimation.tsx/7644b7e4fd" text={"Keep the other seven ends in their own channels."} label="Guide text"/></p>}
    {step==='p99'&&<p className="assembly-parts-legend"><GuideText variant field="prose/ThreadingAnimation.tsx/fc6c288913" text={"Per motor: bottom spool ×1 · M2 nut ×1 · M2×4 screws ×3 · ratchet ×1. Prepare sixteen sets."} label="Guide text"/></p>}
    {step==='p122'&&<p className="assembly-parts-legend"><GuideText variant field="prose/ThreadingAnimation.tsx/e5d98f13b3" text={"Carrier · M2×8 screws ×4 · wrist pulley · 4×10 pin · 4×8×3 bearing · M4 nuts ×3 · M4×10 screws ×3."} label="Guide text"/></p>}
    <label className="assembly-motion-scrubber"><span>Replay any movement</span><input aria-label="Animation progress" type="range" min="0" max="1000" value={Math.round(position*1000)} onChange={e=>{setPlaying(false);setPosition(Number(e.target.value)/1000)}}/></label>
    <p className="assembly-motion-cue" aria-live={playing?'off':'polite'}><><strong>{phase+1}.</strong> {lesson.cues[phase]}</></p>
  </section>
}

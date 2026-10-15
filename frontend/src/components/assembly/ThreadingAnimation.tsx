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
  const [inspection,setInspection]=useState<'rotation'|'axial'|undefined>()
  const canInspect=['p33','p42','p46','p54','p62','p64','p68','p89'].includes(step)
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
  return <section className="assembly-motion assembly-motion-lesson" aria-label={lesson.title}>
    <div className="assembly-row"><div><span className="assembly-eyebrow">SEE HOW IT WORKS</span><h3>{lesson.title}</h3></div><button className="assembly-secondary" aria-label={playing?'Pause animation':'Play animation'} onClick={()=>{if(position>=1)setPosition(0);setPlaying(!playing)}}>{playing?'Ⅱ':'▶'}</button></div>
    {canInspect&&<div className="assembly-clip-tabs">{([undefined,'rotation','axial'] as const).map(mode=><button key={mode??'assemble'} aria-pressed={inspection===mode} onClick={()=>{setInspection(mode);setPosition(0);setPlaying(false)}}>{mode==='rotation'?'Check rotation':mode==='axial'?'Check axial play':'Assemble'}</button>)}</div>}
    {!inspection&&<div className="assembly-motion-phases">{lesson.steps.map((step,i)=><button key={step} aria-pressed={phase===i} onClick={()=>{setInspection(undefined);setPlaying(false);setPosition(step==='p126'?[0,.18,.65][i]:i/3)}}><span>{i+1}</span>{step}</button>)}</div>}
    {['p33','p42','p46','p54','p62','p64','p68','p89','p123','p126'].includes(step)&&!inspection&&<div className="assembly-row"><label><input type="checkbox" checked={channels} onChange={e=>setChannels(e.target.checked)}/> See through the parts</label></div>}
    <div className={`assembly-joint-and-routing ${['p42','p54','p62','p64'].includes(step)?'':'assembly-joint-only'}`}><PartAssemblyMotion build={build} step={step} position={position} tendon={tendon} inspection={inspection} channels={channels}/><TendonRouting build={build} step={step} selectedTendon={tendon} onTendon={setTendon}/></div>
    {!inspection&&['p33','p42','p46','p54','p62','p68'].includes(step)&&<div className="assembly-tendon-legend" aria-label="Tendon color legend">{legend.map(([color,label],i)=>step==='p68'?<button key={label} aria-pressed={tendon===i} onClick={()=>setTendon(i)}><i style={{background:color}}/>{label}</button>:<span key={label}><i style={{background:color}}/>{label}</span>)}</div>}
    {step==='p68'&&!inspection&&<p className="assembly-muted">Select a named tendon to highlight its path. The two white rings mark its TP exit and carpal entrance. Rotate the model to look into the seat; keep the other seven ends in their own channels.</p>}
    <AssemblyComparison step={step} build={build} model={()=><PartAssemblyMotion build={build} step={step} position={position} tendon={tendon} inspection={inspection} channels={channels}/>}/>
    {step==='p99'&&<p className="assembly-parts-legend">Per motor: bottom spool ×1 · M2 nut ×1 · M2×4 screws ×3 · ratchet ×1. Prepare sixteen sets.</p>}
    {step==='p122'&&<p className="assembly-parts-legend">Carrier · M2×8 screws ×4 · wrist pulley · 4×10 pin · 4×8×3 bearing · M4 nuts ×3 · M4×10 screws ×3.</p>}
    <label className="assembly-motion-scrubber"><span>Replay any movement</span><input aria-label="Animation progress" type="range" min="0" max="1000" value={Math.round(position*1000)} onChange={e=>{setPlaying(false);setPosition(Number(e.target.value)/1000)}}/></label>
    <p className="assembly-motion-cue" aria-live={playing?'off':'polite'}>{inspection==='rotation'?'Support the fixed part and keep the tendons slack. Move the joint gently through its available range without forcing its stops. The animation shows the direction of movement, not a calibrated range limit.':inspection==='axial'?'Support the fixed part. Gently push and pull along the bearing axis to feel for looseness. This motion is exaggerated to show the test direction; it is not an acceptable-clearance specification.':<><strong>{phase+1}.</strong> {lesson.cues[phase]}</>}</p>
    <small className="assembly-muted">Drag to inspect; scroll or pinch to zoom. {inspection?'Tendons are hidden during the bearing check; keep the physical strands slack.':step==='p68'?'Follow all eight thumb tendons through the carpals. The six passing strands and both TP anchors keep their own paths to the loose ends below.':step==='p64'?'Follow each AP channel and side anchor into its matching carpal channel. All 24 ends remain free below the carpals.':step==='p89'?'The same 32 cords continue through the carpal and wrist channels. Use the transparent view to trace them to the loose ends below the wrist.':step==='p62'?'Six tendons pass through the shared TP slot between the guide pins; two more leave the TP anchor channels. Use the transparent view to follow all eight.':['p33','p42','p46','p54'].includes(step)?'The DP and PP tendons follow their channels in the seated joint. Use the transparent view to inspect the hidden paths.':['p123','p126'].includes(step)?'The white cord follows the groove and anchor channel. The final phase traces the 5 mm tail back into the channel.':'Colored cords show the exposed spans; use the channel diagrams to match each entrance.'} Bearings and fasteners move along their assembly axes.</small>
  </section>
}

import {useEffect,useState} from 'react'
import {PartAssemblyMotion} from './PartAssemblyMotion'
import type {Build} from './buildContent'

export function JointInspection({build,step}:{build:Build;step:string}){
 const [mode,setMode]=useState<'rotation'|'axial'>('rotation'),[position,setPosition]=useState(0),[playing,setPlaying]=useState(false),[replay,setReplay]=useState(0)
 useEffect(()=>{
  if(!playing)return
  let frame=0,start:number|undefined
  const tick=(time:number)=>{start??=time;const next=Math.min(1,(time-start)/5000);setPosition(next);if(next<1)frame=requestAnimationFrame(tick);else setPlaying(false)}
  frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)
 },[playing,replay])
 return <section className="assembly-joint-inspection" data-contrast={build.version!=='touch'||step==='p89'} aria-label="Joint checks">
  <div className="assembly-clip-tabs">{(['rotation','axial'] as const).map(value=><button key={value} aria-pressed={mode===value} onClick={()=>{setMode(value);setPosition(0);setReplay(n=>n+1);setPlaying(true)}}>{value==='rotation'?'Check rotation':'Check axial play'}</button>)}</div>
  <PartAssemblyMotion build={build} step={step} position={position} inspection={mode}/>
  <label className="assembly-motion-scrubber"><span>{mode==='rotation'?'Full model range':'Bearing axis'}</span><input type="range" aria-label="Joint check progress" min="0" max="1000" value={Math.round(position*1000)} onChange={e=>{setPlaying(false);setPosition(+e.target.value/1000)}}/></label>
  <p>{mode==='rotation'?'Support the fixed part and keep the tendons slack. Move gently through the available range.':'Gently push and pull along the bearing axis to check for looseness. The animation exaggerates this motion.'}</p>
 </section>
}

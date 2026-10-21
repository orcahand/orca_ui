import {useId, useState, type ReactNode} from 'react'
import type {Build} from './buildContent'
import localClips from './local-clips.json'

type Clip={src:string;poster:string;title:string}
export function StepMedia({step,build,children}:{step:string;build:Build;children:ReactNode}) {
  const [video,setVideo]=useState(false),[active,setActive]=useState(0),id=useId()
  const feeTech=build.motor==='feetech'&&['p97','p98','p115'].includes(step)
  const excluded=step==='finishing-pp'||(build.motor==='feetech'&&['p89','p112','p122'].includes(step))
  const clips:Clip[]=feeTech?['Cable connections','Installed motor wiring','Connector orientation'].map((title,i)=>({title,src:`./assembly/media/feetech-video-${i+1}.mp4`,poster:`./assembly/media/feetech-video-${i+1}-poster.jpg`}))
    :excluded?[]:(step==='p37'?['p37','p40']:step==='prepare-pp'?['p33']:step==='thumb-tendons'?['p6']:[step]).flatMap(key=>(localClips as Record<string,Clip[]>)[key]??[]).filter((_,i)=>step==='prepare-pp'?i===0:step==='p33'?i===1:true)
  if(!clips.length)return <>{children}</>
  const clip=clips[active]
  return <section className="assembly-step-media" aria-label="Step guide and video">
    <div className="assembly-media-tabs assembly-clip-tabs" role="tablist" aria-label="Step view" onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?false:e.key==='End'?true:!video;setVideo(next);document.getElementById(`${id}-${next?'video':'guide'}-tab`)?.focus()}}>
      <button role="tab" tabIndex={video?-1:0} id={`${id}-guide-tab`} aria-controls={`${id}-guide`} aria-selected={!video} onClick={()=>setVideo(false)}>Guide</button>
      <button role="tab" tabIndex={video?0:-1} id={`${id}-video-tab`} aria-controls={`${id}-video`} aria-selected={video} onClick={()=>setVideo(true)}>Video</button>
    </div>
    {video?<div role="tabpanel" id={`${id}-video`} aria-labelledby={`${id}-video-tab`} className="assembly-video-section assembly-local-video">
      {clips.length>1&&<div className="assembly-clip-tabs" aria-label="Video clips">{clips.map((c,i)=><button key={c.src} aria-label={c.title} aria-pressed={active===i} onClick={()=>setActive(i)}>{i+1}</button>)}</div>}
      <video key={clip.src} controls playsInline preload="metadata" poster={clip.poster} aria-label={clip.title} src={clip.src}/>
    </div>:<div role="tabpanel" id={`${id}-guide`} aria-labelledby={`${id}-guide-tab`}>{children}</div>}
  </section>
}

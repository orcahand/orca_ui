import {useRef,useState,type ReactNode} from 'react'
import {MEDIA,STEPS} from './guide'
import type {Build} from './buildContent'
import {photoResolution} from './photoResolution'

export function ViewToggle({photo,onChange}:{photo:boolean;onChange:(photo:boolean)=>void}){
 return <div className="assembly-view-toggle" role="group" aria-label="Image view"><button aria-pressed={!photo} onClick={()=>onChange(false)}>3D model</button><button aria-pressed={photo} onClick={()=>onChange(true)}>Photo</button></div>
}

export function AssemblyComparison({step,build,model,photoSources,children}:{step:string;build:Build;model:()=>ReactNode;photoSources?:readonly string[];children?:ReactNode}){
 const dialog=useRef<HTMLDialogElement>(null),[open,setOpen]=useState(false),[index,setIndex]=useState(0),[inline,setInline]=useState(0)
 const photos=(STEPS.find(s=>s.id===step)?.pages??[]).flatMap(p=>MEDIA[String(p)]?.panels??(MEDIA[String(p)]?[{...MEDIA[String(p)],caption:'Assembly photo'}]:[])).filter(p=>!p.side||p.side===build.side).filter(p=>!['finishing-pp','pp-ready'].includes(step)||/panel-036-[45]\.png$/.test(p.src)).filter(p=>!photoSources||photoSources.some(src=>p.src.endsWith('/'+src)))
 const title=STEPS.find(s=>s.id===step)?.title
 function cycle(delta:number){setIndex(i=>(i+delta+photos.length+1)%(photos.length+1))}
 const shown=Math.min(inline,photos.length)
 return <div className="assembly-model-photos">
  <div className="assembly-row">{photos.length>0?<ViewToggle photo={shown>0} onChange={photo=>setInline(photo?1:0)}/>:<span/>}<button className="assembly-text-button" aria-label="Enlarge model and assembly photos" onClick={()=>{setIndex(shown);setOpen(true);dialog.current?.showModal()}}>⤢</button></div>
  {shown===0?children:<figure className="assembly-inline-photo"><img src={photoResolution(photos[shown-1].src)} alt={`Assembly photo ${shown} for ${title}`}/>{photos.length>1&&<div className="assembly-row assembly-image-navigation"><button onClick={()=>setInline(i=>i>1?i-1:photos.length)}>←</button><span>{shown} / {photos.length}</span><button onClick={()=>setInline(i=>i<photos.length?i+1:1)}>→</button></div>}</figure>}
  <dialog ref={dialog} className="assembly-lightbox assembly-model-comparison" data-image-kind={index===0?'cad':'photo'} aria-label="Assembly model and photos" onClose={()=>setOpen(false)} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();cycle(e.key==='ArrowRight'?1:-1)}}}>
   <div className="assembly-row">{photos.length>0?<ViewToggle photo={index>0} onChange={photo=>setIndex(photo?1:0)}/>:<span/>}<button autoFocus onClick={()=>dialog.current?.close()}>Close image ×</button></div>
   {open&&(index===0?<div className="assembly-enlarged-model">{model()}</div>:<img src={photoResolution(photos[index-1].src)} alt={`Assembly photo ${index} for ${title}`}/>)}
   {photos.length>0&&<div className="assembly-row assembly-image-navigation"><button onClick={()=>cycle(-1)}>← Previous image</button><span>{index+1} / {photos.length+1}</span><button onClick={()=>cycle(1)}>Next image →</button></div>}
  </dialog>
 </div>
}

import {useRef,useState,type ReactNode} from 'react'
import {MEDIA,STEPS} from './guide'
import type {Build} from './buildContent'
import {photoResolution} from './photoResolution'

export function AssemblyComparison({step,build,model,photoSources}:{step:string;build:Build;model:()=>ReactNode;photoSources?:readonly string[]}){
 const dialog=useRef<HTMLDialogElement>(null),[open,setOpen]=useState(false),[index,setIndex]=useState(0)
 const photos=(STEPS.find(s=>s.id===step)?.pages??[]).flatMap(p=>MEDIA[String(p)]?.panels??(MEDIA[String(p)]?[{...MEDIA[String(p)],caption:'Assembly photo'}]:[])).filter(p=>!p.side||p.side===build.side).filter(p=>step!=='finishing-pp'||/panel-036-[345]\.png$/.test(p.src)).filter(p=>!photoSources||photoSources.some(src=>p.src.endsWith('/'+src)))
 function cycle(delta:number){setIndex(i=>(i+delta+photos.length+1)%(photos.length+1))}
 return <><button className="assembly-text-button" aria-label="Enlarge model and assembly photos" onClick={()=>{setIndex(0);setOpen(true);dialog.current?.showModal()}}>⤢</button>
  <dialog ref={dialog} className="assembly-lightbox assembly-model-comparison" data-image-kind={index===0?'cad':'photo'} aria-label="Assembly model and photos" onClose={()=>setOpen(false)} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();cycle(e.key==='ArrowRight'?1:-1)}}}>
   <div className="assembly-row"><div className="assembly-clip-tabs"><button aria-pressed={index===0} onClick={()=>setIndex(0)}>Model view</button>{photos.length>0&&<button aria-pressed={index>0} onClick={()=>setIndex(1)}>Assembly photos</button>}</div><button autoFocus onClick={()=>dialog.current?.close()}>Close image ×</button></div>
   {open&&(index===0?<div className="assembly-enlarged-model">{model()}</div>:<img src={photoResolution(photos[index-1].src)} alt={`Assembly photo ${index} for ${STEPS.find(s=>s.id===step)?.title}`}/>)}
   <div className="assembly-row assembly-image-navigation"><button onClick={()=>cycle(-1)}>← Previous image</button><span>{index+1} / {photos.length+1}</span><button onClick={()=>cycle(1)}>Next image →</button></div>
  </dialog>
 </>
}

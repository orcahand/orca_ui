import {useRef,useState} from 'react'
import {GuideText} from './GuideEditing'
import type {Build} from './buildContent'
import {stepPartImages} from './stepPartImages'

export function StepSupplies({step,build,parts,tools}:{step:string;build:Build;parts:string[];tools:string[]}) {
  const dialog=useRef<HTMLDialogElement>(null),[kind,setKind]=useState<'parts'|'tools'>('parts')
  function show(next:'parts'|'tools'){setKind(next);dialog.current?.showModal()}
  return <div className="assembly-step-supplies">
    {parts.length>0&&<button className="assembly-secondary" onClick={()=>show('parts')}>Parts</button>}
    {tools.length>0&&<button className="assembly-secondary" onClick={()=>show('tools')}>Tools</button>}
    <dialog ref={dialog} className="assembly-parts-dialog assembly-step-parts-dialog" aria-label={kind==='parts'?'Parts for this step':'Tools for this step'} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}>
      <div className="assembly-row assembly-parts-dialog-header"><h3>{kind==='parts'?'Parts':'Tools'}</h3><button className="assembly-secondary" autoFocus onClick={()=>dialog.current?.close()}>Close {kind} ×</button></div>
      {kind==='parts'?<div className="assembly-part-detail-grid">{parts.map((item,i)=><figure key={i}>
        <div className="assembly-step-part-images">{stepPartImages(item,build,step).map(image=><img key={image.src} src={image.src} alt={image.label} title={image.label}/>)}</div>
        <figcaption><GuideText field={`${step}/part/${i}`} text={item} label={`Part ${i+1}`}/></figcaption>
      </figure>)}</div>:<ul className="assembly-step-tools">{tools.map((item,i)=><li key={i}><GuideText field={`${step}/tool/${i}`} text={item} label={`Tool ${i+1}`}/></li>)}</ul>}
    </dialog>
  </div>
}

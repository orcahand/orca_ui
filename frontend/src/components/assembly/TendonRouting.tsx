import {useEffect,useState,useRef} from 'react'
import {PartAssemblyMotion} from './PartAssemblyMotion'
import {AssemblyComparison} from './AssemblyComparison'
import {routingDiagram,type RoutingImage} from './routingDiagrams'
import type {Build} from './buildContent'
import {photoResolution} from './photoResolution'
function Face({image,point,color,title}:{image:RoutingImage;point:[number,number]|null;color:string;title:string}){
 const [photo,setPhoto]=useState(false),dialog=useRef<HTMLDialogElement>(null),view=image.view??[0,0,image.width,image.height],r=image.markerRadius??Math.min(view[2],view[3])*.055
 const drawing=<svg viewBox={view.join(' ')} role="img" aria-label={title}><image href={photoResolution(image.src)} width={image.width} height={image.height}/>{point&&<><circle cx={point[0]} cy={point[1]} r={r} fill="none" stroke="#fff" strokeWidth={r*.65}/><circle cx={point[0]} cy={point[1]} r={r} fill="none" stroke={color} strokeWidth={r*.4}/><circle cx={point[0]} cy={point[1]} r={r*1.8} fill="none" stroke={color} strokeWidth={r*.16}/></>}</svg>
 return <figure><figcaption>{title}</figcaption><button className="assembly-image-button" onClick={()=>dialog.current?.showModal()} aria-label={`Enlarge ${title}`}>{drawing}</button><button className="assembly-text-button" aria-label={`Enlarge ${title}`} onClick={()=>dialog.current?.showModal()}>⤢</button><dialog ref={dialog} className="assembly-lightbox assembly-route-dialog" aria-label={title} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}><div className="assembly-row"><span>{title}</span>{image.reference&&<button onClick={()=>setPhoto(!photo)}>{photo?'Model view':'Assembly photo'}</button>}<button autoFocus onClick={()=>dialog.current?.close()}>Close channel ×</button></div>{photo&&image.reference?<svg viewBox={(image.reference.view??[0,0,image.reference.width,image.reference.height]).join(' ')} role="img" aria-label="Assembly photo"><image href={photoResolution(image.reference.src)} width={image.reference.width} height={image.reference.height}/></svg>:drawing}</dialog></figure>
}
export function TendonRouting({step,build,selectedTendon,onTendon,compact=false}:{step:string;build:Build;selectedTendon?:number;onTendon?:(index:number)=>void;compact?:boolean}){
 const diagram=routingDiagram(step,build.side,build.version),[local,setLocal]=useState(0),[playing,setPlaying]=useState(false),[cycle,setCycle]=useState(0)
 useEffect(()=>{if(!playing)return;const timer=setTimeout(()=>setPlaying(false),4000);return()=>clearTimeout(timer)},[playing,cycle])
 if(!diagram)return null
 const trace=['p59','p62'].includes(step)&&!diagram.image.reference
 const selected=selectedTendon??local
 const route=diagram.routes[selected]
 const model=()=> <PartAssemblyMotion build={build} step="p62" position={.35} tendon={selected} channels/>
 return <section className="assembly-routing-lesson" data-contrast={false} aria-label={diagram.title}>
  {!compact&&<><h4>{diagram.title}</h4><p>{diagram.orientation}</p></>}
  <div className="assembly-clip-tabs">{diagram.routes.map((r,i)=><button key={r.name} aria-pressed={i===selected} onClick={()=>{setLocal(i);onTendon?.(i);setCycle(c=>c+1);setPlaying(true)}}><span style={{background:r.color}}/>{i+1} · {r.name}</button>)}</div>
  {step==='p59'&&<div className="assembly-interactive-route">{model()}<AssemblyComparison step="p62" build={build} model={model}/><small>Drag to rotate · scroll or pinch to zoom. Select a tendon to follow its route.</small></div>}
  <div className="assembly-routing-faces"><Face image={diagram.entryImage} point={route.entry} color={route.color} title={compact?'Entry':`${route.name} · ${diagram.entryTitle}`}/><Face image={diagram.exitImage} point={route.exit} color={route.color} title={route.exit?(compact?'Exit':`${route.name} · ${diagram.exitTitle}`):'AP side-anchor pair · check the selected direction with a gentle pull'}/></div>
  {trace&&<div className="assembly-route-trace"><svg viewBox={`0 0 ${diagram.image.width} ${diagram.image.height}`} role="img" aria-label={`${route.name}: follow the highlighted tendon into its channel`}><image href={photoResolution(diagram.image.src)} width={diagram.image.width} height={diagram.image.height}/><path d={route.path} fill="none" stroke="#151b20" strokeWidth="5"/><path d={route.path} fill="none" stroke={route.color} strokeWidth="3"/><path key={cycle} className={playing?'assembly-route-flow':''} d={route.path} fill="none" stroke="#fff" strokeWidth="2" strokeDasharray="12 24"/></svg></div>}
  {trace&&<div className="assembly-row"><strong style={{color:route.color}}>{selected+1} · {route.name}</strong><button className="assembly-text-button" onClick={()=>{if(trace){setCycle(c=>c+1);setPlaying(!playing)}else{const next=(selected+1)%diagram.routes.length;setLocal(next);onTendon?.(next)}}}>{trace?(playing?'Pause route':'Trace this tendon →'):'Next tendon →'}</button></div>}
 </section>
}

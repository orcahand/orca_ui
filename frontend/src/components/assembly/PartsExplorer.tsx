import { Component, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { loadBundle, finishMaterial, type Bundle } from './cadAssets'
import * as THREE from 'three'
import type { Build } from './buildContent'
import { areaSupplyNote, areaSupplyQuantity, supplies, partQuantityLabel, supplyQuantity, supplementalParts, groupStandardParts, type Area, type Part, type Supply } from './assemblyParts'

type Item={part:Part;area:string;nodes:string[]}
type Region={area:Area;x:number;y:number;width:number;height:number}
type Target={x:number;y:number;size:number;labelWidth:number}
type Layout={width:number;height:number;regions:Region[];targets:Map<string,Target>}
function itemsFor(bundle:Bundle):Item[] {
  return groupStandardParts(bundle.inventory.parts).flatMap(part=>part.category==='Tendons'
    ? [{part,area:'Thumb',nodes:part.nodes.slice(0,8)},{part,area:'Fingers',nodes:part.nodes.slice(8)}]
    : Object.entries(part.areas).map(([area,nodes])=>({part,area,nodes})))
}
const itemKey=(item:Item)=>`${item.area}:${item.part.id}`
const isHardware=(part:Part)=>['Standard components','Tendons'].includes(part.category)
function layoutFor(width:number,items:Item[]):Layout {
  const uiScale=Math.min(1,width/1000),height=width*.68,padding=10*uiScale,gap=10*uiScale,available=width-padding*2
  const topHeight=height*.46-gap,lowerY=padding+topHeight+gap,lowerHeight=height-lowerY-padding
  const regions:Region[]=[
    {area:'Thumb',x:padding,y:padding,width:available*.3-gap/2,height:topHeight},
    {area:'Fingers',x:padding+available*.3+gap/2,y:padding,width:available*.7-gap/2,height:topHeight},
    {area:'Carpals',x:padding,y:lowerY,width:available*.25-gap,height:lowerHeight},
    {area:'Wrist',x:padding+available*.25,y:lowerY,width:available*.25-gap,height:lowerHeight},
    {area:'Tower',x:padding+available*.5,y:lowerY,width:available*.5,height:lowerHeight},
  ]
  const targets=new Map<string,Target>()
  for(const region of regions){
    const parts=items.filter(item=>item.area===region.area&&!isHardware(item.part))
    const header=46*uiScale,footer=82*uiScale,labelHeight=28*uiScale,innerHeight=region.height-header-footer
    let columns=1,best=-Infinity
    for(let n=1;n<=Math.max(1,parts.length);n++){
      const rows=Math.ceil(parts.length/n),size=Math.min(region.width/n-14*uiScale,innerHeight/rows-labelHeight-8*uiScale)
      if(size>best){best=size;columns=n}
    }
    const cell=region.width/columns,row=innerHeight/Math.max(1,Math.ceil(parts.length/columns)),size=Math.max(4,Math.min(76*uiScale,best))
    parts.forEach((item,i)=>targets.set(itemKey(item),{x:region.x+(i%columns+.5)*cell,y:region.y+header+Math.floor(i/columns)*row+(row-labelHeight)/2,size,labelWidth:cell-8*uiScale}))
    items.filter(item=>item.area===region.area&&isHardware(item.part)).forEach(item=>targets.set(itemKey(item),{x:region.x+region.width/2,y:region.y+region.height-footer/2,size:0,labelWidth:0}))
  }

  return {width,height,regions,targets}
}
function Model({bundle,build,items,layout,amount,onPart,onSettled}:{bundle:Bundle;build:Build;items:Item[];layout:Layout;amount:number;onPart:(i:Item)=>void;onSettled:(ready:boolean)=>void}) {
  const invalidate=useThree(s=>s.invalidate),camera=useThree(s=>s.camera) as THREE.OrthographicCamera
  const animated=useRef(amount),settled=useRef(false)
  const assembled=amount===0
  const pieces=useMemo(()=>{
    const byNode=new Map<string,Item>();items.forEach(i=>i.nodes.forEach(n=>byNode.set(n,i)))
    bundle.scene.updateMatrixWorld(true)
    const box=new THREE.Box3().setFromObject(bundle.scene),center=box.getCenter(new THREE.Vector3()),extent=box.getSize(new THREE.Vector3())
    const up=extent.x>extent.y&&extent.x>extent.z?new THREE.Matrix4().makeRotationZ(Math.PI/2):extent.z>extent.y?new THREE.Matrix4().makeRotationX(-Math.PI/2):new THREE.Matrix4()
    const view=new THREE.Matrix4().makeRotationY(2.65).multiply(up),quaternion=new THREE.Quaternion().setFromRotationMatrix(view)
    const scale=Math.min(layout.width*.65,layout.height*.86)/Math.max(extent.x,extent.y,extent.z)
    const result:{mesh:THREE.Mesh;origin:THREE.Vector3;item:Item;size:number;scale:number;first:boolean;rotation:THREE.Quaternion}[]=[]
    bundle.scene.traverse(node=>{
      if(!(node instanceof THREE.Mesh))return
      let current:THREE.Object3D|null=node,item:Item|undefined
      while(current&&!item){item=byNode.get(current.name);current=current.parent}
      if(!item)return
      node.geometry.computeBoundingBox()
      const localCenter=node.geometry.boundingBox!.getCenter(new THREE.Vector3())
      const origin=localCenter.clone().applyMatrix4(node.matrixWorld).sub(center).applyMatrix4(view).multiplyScalar(scale)
      const mesh=new THREE.Mesh(node.geometry,finishMaterial(item.part,build,node.geometry));mesh.quaternion.copy(quaternion)
      const projected=node.geometry.boundingBox!.clone().applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(.55,-.65,.08)));const dimensions=projected.getSize(new THREE.Vector3());const size=Math.max(dimensions.x,dimensions.y)
      result.push({mesh,origin,item,size,scale,rotation:quaternion.clone(),first:!result.some(p=>itemKey(p.item)===itemKey(item!))})
    })
    return result
  },[bundle,build,items,layout.width,layout.height])
  useEffect(()=>()=>pieces.forEach(p=>(p.mesh.material as THREE.Material).dispose()),[pieces])
  useEffect(()=>{camera.position.set(0,0,1400);camera.lookAt(0,0,0);camera.zoom=1;camera.updateProjectionMatrix();invalidate()},[assembled,layout.height,camera,invalidate])
  useLayoutEffect(()=>{settled.current=false;onSettled(false);invalidate()},[amount,layout,invalidate,onSettled])
  useFrame(({size},delta)=>{
    const t=window.matchMedia('(prefers-reduced-motion: reduce)').matches?amount:THREE.MathUtils.damp(animated.current,amount,7,delta);animated.current=t
    for(const p of pieces){
      const target=layout.targets.get(itemKey(p.item)),material=p.mesh.material as THREE.MeshStandardMaterial
      const hardware=isHardware(p.item.part),end=target??{x:layout.width/2,y:layout.height/2,size:0}
      p.mesh.position.copy(p.origin).add(new THREE.Vector3(0,0,0)).lerp(new THREE.Vector3(end.x-layout.width/2,layout.height/2-end.y,0),t)
      p.mesh.quaternion.copy(p.rotation).slerp(new THREE.Quaternion().setFromEuler(new THREE.Euler(.55,-.65,.08)),t)
      p.mesh.scale.setScalar(THREE.MathUtils.lerp(p.scale,end.size/Math.max(p.size,.01),t))
      material.opacity=hardware||!p.first?1-t:1;material.transparent=material.opacity<.999;material.depthWrite=material.opacity>.8;p.mesh.visible=material.opacity>.015
    }
    const ready=amount===1&&Math.abs(t-amount)<.001&&Math.abs(size.width-layout.width)<1&&Math.abs(size.height-layout.height)<1
    if(ready!==settled.current){settled.current=ready;onSettled(ready)}
    if(Math.abs(t-amount)>.001)invalidate()
  })
  return <>{pieces.map((p,i)=><primitive key={i} object={p.mesh} onClick={(e:{stopPropagation:()=>void})=>{e.stopPropagation();onPart(p.item)}}/>)}<OrbitControls enabled={amount===0} enablePan={false} minZoom={.7} maxZoom={2.4}/></>
}
class ModelBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return {failed:true}}render(){return this.state.failed?<p className="assembly-model-fallback">The model could not be displayed. The bill of materials is available below.</p>:this.props.children}}
export function SupplyIcon({kind}:{kind:Supply['kind']|'hardware'}) {
  return <svg viewBox="0 0 60 45" aria-hidden="true">{kind==='tube'?<><path d="M12 27 46 14" stroke="#b0c5ce" strokeWidth="11"/><ellipse cx="12" cy="27" rx="5" ry="7" fill="#d6e5eb" transform="rotate(-25 12 27)"/><ellipse cx="12" cy="27" rx="2" ry="4" fill="#677e8b" transform="rotate(-25 12 27)"/></>:kind==='cord'?<path d="M6 30 C17 0 47 2 47 20 S17 43 18 25 S44 29 56 15" fill="none" stroke="#298591" strokeWidth="3"/>:kind==='cable'?<><path d="M10 13 C40 13 10 34 50 34" fill="none" stroke="#8d7458" strokeWidth="4"/><rect x="4" y="7" width="12" height="12" rx="2" fill="#536b77"/><rect x="45" y="28" width="12" height="12" rx="2" fill="#536b77"/></>:<g fill="#8096a3"><path d="m13 6 8 5v10l-8 5-8-5V11Z"/><path d="m34 16 11 0v23H34Z"/><rect x="27" y="11" width="24" height="7" rx="3"/><circle cx="13" cy="16" r="4" fill="#d9e3e8"/></g>}</svg>
}
export function PartsExplorer({build}:{build:Build}) {
  const key=`${build.version}-${build.side}-${build.motor}`
  const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false),[amount,setAmount]=useState(0),[width,setWidth]=useState(1000)
  const [detail,setDetail]=useState<{title:string;items:Item[];supplies:Supply[];area?:Area}|null>(null),[query,setQuery]=useState('')
  const [retry,setRetry]=useState(0),[settled,setSettled]=useState(false)
  const hasArchive=(build.version==='base'||build.version==='touch')&&build.motor==='dynamixel'
  const stage=useRef<HTMLDivElement>(null),dialog=useRef<HTMLDialogElement>(null)
  const bundle=loaded?.key===key?loaded.bundle:null
  const items=useMemo(()=>bundle?itemsFor(bundle):[],[bundle]),stock=useMemo(()=>supplies(build),[build])
  const layout=useMemo(()=>layoutFor(width,items),[width,items])
  useEffect(()=>{let active=true;setFailed(false);setAmount(0);setDetail(null);dialog.current?.close();loadBundle(key).then(bundle=>{if(active)setLoaded({key,bundle})}).catch(()=>{if(active)setFailed(true)});return()=>{active=false}},[key,retry])
  useEffect(()=>{if(!stage.current)return;const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));observer.observe(stage.current);return()=>observer.disconnect()},[])
  useLayoutEffect(()=>{if(detail&&!dialog.current?.open)dialog.current?.showModal()},[detail])
  function inspect(area:Area,kind?:'standard'|'cord'|'tube'|'cable'){
    const label=kind==='standard'?'standard components':kind==='cord'?'tendons':kind==='tube'?'PTFE tubes':kind==='cable'?'cables':'all parts'
    setDetail({title:`${area} · ${label}`,area,
      items:items.filter(i=>i.area===area&&i.part.category!=='Tendons'&&(!kind||(kind==='standard'&&i.part.category==='Standard components'))),
      supplies:stock.filter(s=>s.areas.includes(area)&&(!kind||(kind==='standard'?!!s.partLabel:s.kind===kind)))})
  }
  const opacity=amount===1&&settled?1:0
  const bom=groupStandardParts(bundle?.inventory.parts??[]).filter(p=>p.category!=='Tendons')
  const rows=[...bom.map(p=>({id:p.id,label:p.label,quantity:partQuantityLabel(p,stock),category:p.category,areas:[...new Set([...Object.keys(p.areas),...supplementalParts(p,stock).flatMap(s=>s.areas)])].join(', '),note:supplementalParts(p,stock).map(s=>s.note).join(' '),part:p,supply:null as Supply|null})),...stock.filter(s=>!bom.some(p=>p.label===s.partLabel)).map(s=>({id:s.id,label:s.label,quantity:supplyQuantity(s),category:s.kind==='equipment'?'Tools & supplies':s.kind==='hardware'?'Other components':'Cables & consumables',areas:s.areas.join(', '),note:s.note,part:null,supply:s}))]
  // The control board is required even when absent from an individual assembly export.
  if(bundle&&!bom.some(p=>p.label==='OH control board'))rows.push({id:'oh-board',label:'OH control board',quantity:'1',category:'Drive & electronics',areas:'Tower',note:'Required for the completed hand.',part:null,supply:{id:'oh-board',label:'OH control board',quantity:'1',kind:'hardware',areas:['Tower'],note:'Required for the completed hand.',image:'./assembly/parts/base-right-dynamixel/e2fd92904c.png'}})
  const visibleRows=rows.filter(r=>`${r.label} ${r.category} ${r.areas}`.toLowerCase().includes(query.toLowerCase()))
  function download(){const quote=(v:string)=>`"${v.replaceAll('"','""')}"`;const csv=[['Part','Quantity','Used in','Notes'],...rows.map(r=>[r.label,r.quantity,r.areas,r.note])].map(r=>r.map(quote).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`orca-${key}-bom.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  return <section className="assembly-parts-explorer" aria-label="Explore your hand and parts">
    <div ref={stage} className="assembly-area-stage">
      <div className="assembly-cad-toolbar"><div><span className="assembly-eyebrow">YOUR HAND · ASSEMBLY BY ASSEMBLY</span><p>{amount===0?'Drag to turn. Move the slider to explore inside.':'Select standard components, tendons or PTFE to see the quantities for each area.'}</p></div></div>
      {!bundle?<div className="assembly-cad-placeholder" role="status">{failed?(hasArchive?<div className="assembly-model-recovery"><h3>The 3D model could not load</h3><p>The UI normally unpacks this model automatically when it starts. If the model files have not been extracted, restart the UI or run this from your <code>orca_ui</code> checkout:</p><code className="assembly-recovery-command">uv run python -m orca_ui.assembly_assets</code><p>The archive for your selection is <code>orca_ui/models/assembly/{key}.zip</code>. You can also unzip its <code>assembly.glb</code> into <code>orca_ui/webui/assembly/parts/{key}/</code>. For frontend development, extract it into <code>frontend/public/assembly/parts/{key}/</code> too.</p><button type="button" className="assembly-secondary" onClick={()=>setRetry(n=>n+1)}>Retry model</button></div>:'The complete assembly for this configuration is not available yet.'):'Loading the detailed assembly…'}</div>:<div className="assembly-area-scroll"><div className="assembly-area-canvas" style={{height:layout.height,'--explorer-scale':Math.min(1,width/1000)} as React.CSSProperties}>
        <ModelBoundary key={key}><Canvas orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1400],zoom:1,near:.1,far:5000}} gl={{alpha:true,antialias:true}} aria-label={`${build.version} ${build.side} hand assembly`}><ambientLight intensity={1.2}/><hemisphereLight args={['#f5f9ff','#6d7e88',1.5]}/><directionalLight position={[300,450,850]} intensity={3}/><directionalLight position={[-400,120,-500]} intensity={2}/><Model bundle={bundle} build={build} items={items} layout={layout} amount={amount} onSettled={setSettled} onPart={item=>setDetail({title:item.part.label,items:[item],supplies:[]})}/></Canvas></ModelBoundary>
        <div className="assembly-area-overlays" inert={!opacity} style={{opacity,pointerEvents:opacity?'auto':'none'}} aria-hidden={!opacity}>
          {layout.regions.map(region=><section key={region.area} className="assembly-area-outline" style={{left:region.x,top:region.y,width:region.width,height:region.height}}><button className="assembly-area-title" tabIndex={opacity?0:-1} onClick={()=>inspect(region.area)}>{region.area}<span>↗</span></button><div className="assembly-area-icons"><button tabIndex={opacity?0:-1} onClick={()=>inspect(region.area,'standard')} aria-label={`${region.area} standard components`}><SupplyIcon kind="hardware"/><span>Hardware</span></button>{(['cord','tube','cable'] as const).filter(kind=>stock.some(s=>s.kind===kind&&s.areas.includes(region.area))).map(kind=><button key={kind} tabIndex={opacity?0:-1} onClick={()=>inspect(region.area,kind)} aria-label={`${region.area} ${kind==='cord'?'tendons':kind==='tube'?'PTFE':'cables'}`}><SupplyIcon kind={kind}/><span>{kind==='cord'?'Tendons':kind==='tube'?'PTFE':'Cables'}</span></button>)}</div></section>)}
          {items.filter(i=>!isHardware(i.part)).map(item=>{const point=layout.targets.get(itemKey(item));return point&&<button tabIndex={opacity?0:-1} className="assembly-area-part-label" title={item.part.label} key={itemKey(item)} style={{left:point.x-point.labelWidth/2,top:point.y+point.size/2+3*Math.min(1,width/1000),width:point.labelWidth}} onClick={()=>setDetail({title:item.part.label,items:[item],supplies:[]})}>{item.part.label}{item.nodes.length>1&&<strong> ×{item.nodes.length}</strong>}</button>})}
        </div>
      </div></div>}
      <label className="assembly-area-slider"><span>Assembled</span><input aria-label="Explode assembly" type="range" min="0" max="100" value={Math.round(amount*100)} disabled={!bundle} onChange={e=>setAmount(Number(e.target.value)/100)}/><span>Exploded</span><output>{Math.round(amount*100)}%</output></label>
    </div>
    <details className="assembly-bom" aria-label="Full bill of materials"><summary><h3>Bill of materials</h3><span>Expand full list</span></summary><div className="assembly-row"><div><p className="assembly-muted">{build.side} hand · {build.motor} · {build.version} · {rows.length} line items</p></div><button className="assembly-secondary" disabled={!bundle} onClick={download}>Download CSV ↓</button></div>
      {!bundle&&<p>The complete parts list needs the matching assembly. Cables and consumables are shown below.</p>}
      <label className="assembly-bom-search"><span className="assembly-sr-only">Find a BOM item</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find a part, size or assembly…"/></label>
      <div className="assembly-bom-table"><table><thead><tr><th>Part / material</th><th>Quantity</th><th>Used in</th></tr></thead><tbody>{visibleRows.map(row=><tr key={row.id}><td>{(row.part?.thumbnail||row.supply?.image)&&<img className="assembly-bom-thumbnail" src={row.part?.thumbnail??row.supply?.image} alt=""/>}{row.part?<button className="assembly-text-button" onClick={()=>setDetail({title:row.label,items:[{part:row.part!,area:'',nodes:row.part!.nodes}],supplies:[]})}>{row.label}</button>:row.supply?<button className="assembly-text-button" onClick={()=>setDetail({title:row.label,items:[],supplies:[row.supply!]})}>{row.label}</button>:row.label}{row.note&&<small>{row.note}</small>}</td><td>{row.quantity}</td><td>{row.areas||'Workbench'}</td></tr>)}</tbody></table>{!visibleRows.length&&<p>No matching parts.</p>}</div>
    </details>
    <dialog ref={dialog} className="assembly-parts-dialog" aria-label={detail?.title??'Assembly parts'} onClose={()=>setDetail(null)} onCancel={e=>e.stopPropagation()}>
      <div className="assembly-row assembly-parts-dialog-header"><div><span className="assembly-eyebrow">{build.side.toUpperCase()} HAND · {build.motor.toUpperCase()} · {build.version.toUpperCase()}</span><h3>{detail?.title}</h3></div><button autoFocus className="assembly-secondary" onClick={()=>dialog.current?.close()}>Close parts ×</button></div>
      <div className="assembly-part-detail-grid">{detail?.items.map(item=><figure key={itemKey(item)}><img src={item.part.thumbnail} alt={item.part.label}/><figcaption><span>{item.part.label}</span><strong>×{partQuantityLabel(item.part,stock,item.area||undefined)}</strong></figcaption>{supplementalParts(item.part,stock,item.area||undefined).map(s=><p key={s.id}>{s.note}</p>)}</figure>)}{detail?.supplies.filter(s=>!detail.items.some(i=>i.part.label===s.partLabel&&(!i.area||s.areas.includes(i.area as Area)))).map(s=><figure key={s.id}><img src={s.image} alt={s.label}/><figcaption><span>{s.label}</span><strong>{s.partLabel?'×':''}{detail.area?areaSupplyQuantity(s,detail.area):supplyQuantity(s)}</strong></figcaption><p>{detail.area?areaSupplyNote(s,detail.area):s.note}</p>{s.files?.map(file=><a key={file.src} className="assembly-text-button" href={file.src} download>Download {file.label} ↓</a>)}</figure>)}</div>
      {detail?.area&&detail.supplies.some(s=>s.kind==='cord')&&['Fingers','Thumb'].includes(detail.area)&&<div className="assembly-area-tendons"><h4>Tendon groups</h4>{(detail.area==='Thumb'?['Thumb']:['Index','Middle','Ring','Pinky']).map(finger=><div key={finger}><strong>{finger}</strong><p>DP flex · DP ext · PP flex · PP ext · AP toward pinky · AP toward thumb{finger==='Thumb'?' · TP flex · TP ext':''}</p><img src="./assembly/supplies/cord.svg" alt={`${finger} tendon cord`}/></div>)}</div>}
      {detail?.supplies.some(s=>s.kind==='cord')&&<p className="assembly-consumable-note">Tendons and shared cables pass through several assemblies. They are counted once in the total BOM. Routing icons show the material, not an exact cable shape.</p>}
    </dialog>
  </section>
}

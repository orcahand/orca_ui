import {GuideText} from './GuideEditing'
import {useEffect,useLayoutEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {Html} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,fade} from './cadScene'
import {conduitData,vectors} from './conduitPaths'
import {TENDONS} from './guide'
import {jointName} from './driveMap'
import type {Build} from './buildContent'

export function wristRoutingOrder(build:Build){
 const data=conduitData(build)
 // The two facing views share screen-left = world +X. Keep the measured row mapping.
 return Array.from({length:32},(_,i)=>i).sort((a,b)=>data.carpals[b].at(-1)![0]-data.carpals[a].at(-1)![0])
}
const routeColor=(index:number)=>index<16?'#b55031':'#147d8e'
const routeName=(index:number)=>{const code=TENDONS[index],direction=code.split('-')[2];return `${jointName(code)} · ${direction==='flex'?'flexion':direction==='ext'?'extension':direction==='p'?'toward pinky':'toward thumb'}`}
function RoutingFace({bundle,build,face,selected,onSelect,closeUp}:{bundle:Bundle;build:Build;face:'carpals'|'wrist';selected:number;closeUp:boolean;onSelect:(i:number)=>void}){
 const {camera,size,invalidate}=useThree()
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),group=new THREE.Group()
  const visible=pieces.filter(p=>face==='carpals'?['Carpals','Touch carpals','Carpal core'].includes(p.part.label):p.part.label==='Wrist frame')
  visible.forEach(p=>{group.add(p.object);fade(p,1)})
  const box=new THREE.Box3().setFromObject(group),center=box.getCenter(new THREE.Vector3())
  const points=conduitData(build)[face].map(p=>vectors(p)[face==='carpals'?p.length-1:0])
  return {pieces,group,box,center,points}
 },[bundle,build,face])
 useLayoutEffect(()=>{
  const c=camera as THREE.OrthographicCamera,extent=scene.box.getSize(new THREE.Vector3())
  const target=closeUp?new THREE.Box3().setFromPoints(scene.points).getCenter(new THREE.Vector3()):scene.center
  c.position.copy(target).add(new THREE.Vector3(0,face==='carpals'?-300:300,0));c.up.set(0,0,face==='carpals'?-1:1);c.lookAt(target)
  const closeExtent=new THREE.Box3().setFromPoints(scene.points).getSize(new THREE.Vector3())
  const half=closeUp?Math.max(closeExtent.z/2+12,(closeExtent.x/2+6)*size.height/size.width):Math.max(extent.z/2+10,(extent.x/2+8)*size.height/size.width)
  c.left=-half*size.width/size.height;c.right=-c.left;c.top=half;c.bottom=-half;c.zoom=1;c.updateProjectionMatrix();invalidate()
 },[camera,size.width,size.height,scene,face,closeUp,invalidate])
 useEffect(()=>()=>disposePieces(scene.pieces),[scene])
 return <><primitive object={scene.group}/>{scene.points.map((point,i)=>{
  const position=point.clone();position.y+=face==='carpals'?-1:1
  const active=selected===i
  return <group key={i} position={position}>
   <mesh rotation={[Math.PI/2,0,0]} renderOrder={2} onClick={e=>{e.stopPropagation();onSelect(i)}}>
    <ringGeometry args={[active?.78:.5,active?1.12:.7,48]}/><meshBasicMaterial color={routeColor(i)} transparent opacity={active?1:.45} depthTest={false} depthWrite={false} side={THREE.DoubleSide}/>
   </mesh>
   <mesh onClick={e=>{e.stopPropagation();onSelect(i)}}><sphereGeometry args={[1.2,12,12]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/></mesh>
   {active&&<Html center position={[0,face==='carpals'?-2:2,face==='carpals'?(i<16?7:-7):(i<16?-7:7)]}><span className="assembly-routing-pin" style={{background:routeColor(i)}}>{i+1}</span></Html>}
  </group>
 })}</>
}

export function WristRouting({build,routeIndex=0,onRoute}:{build:Build;routeIndex?:number;onRoute?:(index:number)=>void}){
 const [position,setLocalPosition]=useState(Math.max(0,Math.min(31,Number.isFinite(routeIndex)?routeIndex:0))),[closeUp,setCloseUp]=useState(false),[loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
 const setPosition=(next:number)=>{setLocalPosition(next);onRoute?.(next)}
 const order=useMemo(()=>wristRoutingOrder(build),[build]),selected=order[position],palm=selected>=16
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 const onSelect=(index:number)=>setPosition(order.indexOf(index))
 return <section className="assembly-wrist-routing" data-contrast={false} aria-label="Match carpal exits to wrist entries">
  <div className="assembly-row"><div></div><span className="assembly-routing-count">{position+1} / 32</span></div>
  <p><GuideText variant field="prose/WristRouting.tsx/4883077353" text={"Keep the pictured orientation: left on the carpal view matches left on the wrist view. Work across the adjacent exits, alternating rows as shown."} label="Guide text"/></p>
  <div className="assembly-clip-tabs"><button aria-pressed={!closeUp} onClick={()=>setCloseUp(false)}>Whole parts</button><button aria-pressed={closeUp} onClick={()=>setCloseUp(true)}>Channel close-up</button></div>
  <div className="assembly-wrist-pair">
   {(['carpals','wrist'] as const).map(face=><figure key={face}>
    <figcaption><GuideText variant field="prose/WristRouting.tsx/7c7a411178" text={[String(face==='carpals'?'1 · Carpal exit':'2 · Wrist entry'),String(face==='carpals'?'Look at the underside':'Look down into the wrist')].join('').trim()} label="Guide text"/></figcaption>
    <div className="assembly-wrist-face"><span className="assembly-wrist-face-label">{face==='carpals'?'Palm · palmar':'Back · dorsal'}</span>
     {loaded?.key===key?<Canvas orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,300,0],near:.1,far:1000}}><ambientLight intensity={1.8}/><directionalLight position={[70,face==='carpals'?-150:150,80]} intensity={2.5}/><RoutingFace bundle={loaded.bundle} build={build} face={face} selected={selected} onSelect={onSelect} closeUp={closeUp}/></Canvas>:<p>{failed?'The model could not load. Reopen this step to retry.':'Loading the channel view…'}</p>}
     <span className="assembly-wrist-face-label bottom">{face==='carpals'?'Back · dorsal':'Palm · palmar'}</span>
    </div>
   </figure>)}
  </div>
  <div className="assembly-routing-selection" style={{borderColor:routeColor(selected)}}><strong>Tendon {selected+1} · {routeName(selected)}</strong><span>{palm?'Palmar carpal row → dorsal wrist entry':'Dorsal carpal row → palmar wrist entry'}</span></div>
  <div className="assembly-route-order" aria-label="Left-to-right threading sequence">{order.map((index,n)=><button key={index} aria-label={`Route ${n+1}: tendon ${index+1}, ${TENDONS[index]}`} aria-pressed={n===position} onClick={()=>setPosition(n)} style={{'--route-color':routeColor(index)} as React.CSSProperties}>{n+1}</button>)}</div>
  <div className="assembly-row"><button className="assembly-secondary" disabled={position===0} onClick={()=>setPosition(position-1)}>← Previous tendon</button><button className="assembly-primary" disabled={position===31} onClick={()=>setPosition(position+1)}>Next tendon →</button></div>
  <p className="assembly-muted"><GuideText variant field="prose/WristRouting.tsx/335aaadf9d" text={"Keep each strand untangled and retain the same order within each row."} label="Guide text"/></p>
  {(build.version==='full'||build.motor==='feetech')&&<p className="assembly-muted"><GuideText variant field="prose/WristRouting.tsx/62646550a1" text={["Reference geometry: ",String(build.version==='touch'?'Touch':'Base')," Dynamixel. The channel layout for ",String(build.version==='full'?'Full': 'FeeTech')," has not been verified against a separate model here."].join('').trim()} label="Guide text"/></p>}
 </section>
}

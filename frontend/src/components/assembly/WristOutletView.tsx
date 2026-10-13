import {useEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {Html,OrbitControls} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,TENDON_COLORS} from './cadScene'
import {wristOutlet} from './wristChannels'
import type {Build} from './buildContent'
function Outlets({bundle,build,selected,expanded=false}:{bundle:Bundle;build:Build;selected:number;expanded?:boolean}){
 const size=useThree(s=>s.size),scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),wrist=pieces.find(p=>p.part.label==='Wrist frame')!,group=new THREE.Group(),center=wrist.bounds.getCenter(new THREE.Vector3());wrist.object.traverse(n=>{if(n instanceof THREE.Mesh){const mat=n.material as THREE.MeshStandardMaterial;mat.color.set('#b5c9cf');mat.roughness=.65}});wrist.object.position.sub(center);group.add(wrist.object)
  group.quaternion.setFromRotationMatrix(new THREE.Matrix4().set(-1,0,0,0,0,0,-1,0,0,-1,0,0,0,0,0,1));return {pieces,group,center}
 },[bundle,build]);useEffect(()=>()=>disposePieces(scene.pieces),[scene])
 return <group scale={Math.min((size.width-44)/95,(size.height-58)/110)}><primitive object={scene.group}>{Array.from({length:32},(_,i)=>{const position=new THREE.Vector3(...wristOutlet(build.side,i)).sub(scene.center);position.y-=1;return <group key={i} position={position}><mesh rotation={[Math.PI/2,0,0]}><ringGeometry args={[i===selected?1.2:.5,i===selected?1.75:.75,24]}/><meshBasicMaterial color={i===selected?TENDON_COLORS[i%8]:'#367c89'} side={THREE.DoubleSide} depthTest={false}/></mesh>{(expanded||i===selected)&&<Html position={[0,-1,0]} center><span className={`assembly-outlet-label ${i===selected?'active':''}`} style={{display:'block',fontSize:expanded&&size.width<520?9:undefined,transform:`translateY(${Math.sign(position.z)*(Math.abs(wristOutlet(build.side,i)[2])>35?1:-1)*(expanded&&size.width<520?18+(i%2)*13:18)}px)`}}>{i+1}</span></Html>}</group>})}{[-1,1].map(sign=><Html key={sign} center position={new THREE.Vector3(-10,50,sign*51).sub(scene.center)} className="assembly-outlet-face">{sign<0?'Palm':'Back'}</Html>)}</primitive></group>
}
export function WristOutletView({build,selected}:{build:Build;selected:number}){
 const dialog=useRef<HTMLDialogElement>(null),[expanded,setExpanded]=useState(false)
 const [bundle,setBundle]=useState<Bundle|null>(null),[failed,setFailed]=useState(false)
 useEffect(()=>{let live=true;loadBundle('base-right-dynamixel').then(b=>{if(live)setBundle(b)}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[])
 const model=(large=false)=>bundle?<Canvas orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}}><ambientLight intensity={1.7}/><directionalLight position={[200,300,500]} intensity={3}/><Outlets bundle={bundle} build={build} selected={selected} expanded={large}/><OrbitControls enablePan minZoom={.8} maxZoom={3}/></Canvas>:<p>{failed?'The wrist view could not load. Reopen this step to retry.':'Loading wrist outlets…'}</p>
 return <figure className="assembly-wrist-outlets"><div className="assembly-wrist-outlet-canvas">{model()}</div><button className="assembly-text-button" onClick={()=>{setExpanded(true);dialog.current?.showModal()}}>Enlarge and show all outlet numbers ⤢</button><dialog ref={dialog} className="assembly-lightbox assembly-outlet-dialog" aria-label="All wrist outlet numbers" onClose={()=>setExpanded(false)} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}><div className="assembly-row"><h3>All 32 wrist outlets · {build.side} hand</h3><button autoFocus onClick={()=>dialog.current?.close()}>Close view ×</button></div>{expanded&&<div className="assembly-wrist-outlet-canvas">{model(true)}</div>}</dialog></figure>
}

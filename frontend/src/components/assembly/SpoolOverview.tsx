import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {Html,OrbitControls} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,fade,nearest} from './cadScene'
import type {Build} from './buildContent'

const GROUPS=[
 {title:'Motor',labels:['Dynamixel XC330 motor'],description:'One motor drives one joint through a pair of opposing tendons.',offset:0},
 {title:'Bottom spool',labels:['Bottom spool','M2 hex nut','M2 × 4 socket screw'],description:'The spool nearest the motor. It is already fixed to the output with three screws. Anchor the first tendon here.',offset:10},
 {title:'Ratchet',labels:['Ratchet'],description:'The toothed piece fitted to the bottom spool. It engages the top tensioner during adjustment.',offset:19},
 {title:'Top spool and tensioner',labels:['Top spool / tensioner','Spool cover','Spool ORCA insert'],description:'The outer spool assembly. It holds the opposing tendon from the same joint and is fitted after the bottom tendon.',offset:31},
 {title:'Bearing and screw',labels:['Bearing · 4 × 8 × 3','M2.5 × 8 socket screw'],description:'Seat the bearing in the loose top spool on the bench. Then fit the prepared spool and secure it with its matching screw.',offset:47},
]
function SpoolStack({bundle,build,amount,selected}:{bundle:Bundle;build:Build;amount:number;selected:number}){
 const wrapper=useRef<THREE.Group>(null),size=useThree(s=>s.size),invalidate=useThree(s=>s.invalidate)
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),motors=pieces.filter(p=>p.part.label==='Dynamixel XC330 motor'),motor=motors.find(p=>p.center.z<0)!,axis=new THREE.Vector3(0,0,-1)
  const group=new THREE.Group(),parts=pieces.filter(p=>GROUPS.some(g=>g.labels.includes(p.part.label))&&nearest(motors,p.center)===motor&&p.center.distanceTo(motor.center)<36)
  parts.forEach(p=>group.add(p.object));group.position.copy(motor.center).negate()
  const view=new THREE.Group();view.add(group);view.rotation.set(2.0,0,.12)
  return {pieces,parts,view,group,axis}
 },[bundle,build])
 useLayoutEffect(()=>{
  scene.parts.forEach(p=>{
   const index=GROUPS.findIndex(g=>g.labels.includes(p.part.label))
   p.object.position.copy(scene.axis).multiplyScalar(GROUPS[index].offset*amount)
   fade(p,selected<0||selected===index?1:.17)
  })
  const w=wrapper.current!;w.scale.setScalar(1);w.position.set(0,0,0);w.updateMatrixWorld(true)
  // Frame the fully exploded assembly so sliding never changes the illustration's scale.
  const box=new THREE.Box3();scene.parts.forEach(p=>{const old=p.object.position.clone();p.object.position.copy(scene.axis).multiplyScalar(GROUPS[GROUPS.findIndex(g=>g.labels.includes(p.part.label))].offset);scene.view.updateMatrixWorld(true);box.union(new THREE.Box3().setFromObject(p.object));p.object.position.copy(old)})
  scene.view.updateMatrixWorld(true)
  const extent=box.getSize(new THREE.Vector3()),center=new THREE.Box3().setFromObject(scene.view).getCenter(new THREE.Vector3()),scale=Math.min((size.width-65)/extent.x,(size.height-45)/extent.y)
  w.scale.setScalar(scale);w.position.copy(center).multiplyScalar(-scale);invalidate()
 },[amount,selected,scene,size.width,size.height,invalidate])
 useEffect(()=>()=>disposePieces(scene.pieces),[scene])
 return <group ref={wrapper}><primitive object={scene.view}><primitive object={scene.group}>{GROUPS.map((g,i)=>{const part=scene.parts.find(p=>g.labels.includes(p.part.label))!;return amount<.55&&selected!==i?null:<Html key={g.title} center position={part.center.clone().addScaledVector(scene.axis,g.offset*amount).add(new THREE.Vector3(22,0,0))}><span className="assembly-spool-number">{i+1}</span></Html>})}</primitive></primitive></group>
}
export function SpoolOverview({build}:{build:Build}){
 const [amount,setAmount]=useState(.8),[selected,setSelected]=useState(-1),[loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 useEffect(()=>{if(build.motor!=='dynamixel')return;let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key,build.motor])
 return <section className="assembly-spool-overview" data-contrast={false} aria-label="Understand the two spools">
  <span className="assembly-eyebrow">Before you wind</span><h3>One motor. Two opposing tendons.</h3>
  <p><strong>Bottom</strong> means closest to the motor. <strong>Top</strong> means farther out along the same shaft. These names describe the two spools on each motor, not its position in the tower.</p>
  <div className="assembly-spool-overview-layout">
   <div className="assembly-spool-overview-model">
    {build.motor==='dynamixel'?<><div className="assembly-spool-overview-canvas">{loaded?.key===key?<Canvas orthographic frameloop="demand" camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.8}/><directionalLight position={[-120,200,300]} intensity={3}/><SpoolStack bundle={loaded.bundle} build={build} amount={amount} selected={selected}/><OrbitControls enablePan={false} minZoom={.7} maxZoom={2.5}/></Canvas>:<p>{failed?'The spool model could not load. Reopen this step to retry.':'Loading the spool assembly…'}</p>}</div><label className="assembly-spool-explode"><span>Assembled</span><input aria-label="Explode the spool assembly" type="range" min="0" max="100" value={Math.round(amount*100)} onChange={e=>setAmount(Number(e.target.value)/100)}/><span>Exploded</span></label></>:<svg viewBox="0 0 360 350" className="assembly-spool-principle" role="img" aria-label="Spool positions along the motor shaft: bottom nearest the motor, top farther out">
     <rect x="125" y="230" width="110" height="90" rx="14" fill="#29333b"/><text x="180" y="280" textAnchor="middle" fill="white">Motor</text><path d="M180 240V56" stroke="#a8b1b5" strokeWidth="12"/><ellipse cx="180" cy="197" rx="68" ry="20" fill="#197f90"/><ellipse cx="180" cy="110" rx="68" ry="20" fill="#b97732"/><text x="180" y="171" textAnchor="middle">Bottom · near motor</text><text x="180" y="78" textAnchor="middle">Top · outer spool</text><path d="M60 120H110M250 205H300" stroke="#647c80" strokeWidth="3"/><text x="180" y="343" textAnchor="middle" fontSize="12">Position diagram · use the supplied FeeTech parts</text>
    </svg>}
   </div>
   <ol className="assembly-spool-key">{GROUPS.map((g,i)=><li key={g.title}><button aria-pressed={selected===i} onClick={()=>setSelected(selected===i?-1:i)}><span>{i+1}</span><div><strong>{g.title}</strong><p>{g.description}</p></div></button></li>)}</ol>
  </div>
  <div className="assembly-spool-sequence"><span><b>1</b> Anchor the bottom tendon</span><span><b>2</b> Fit its opposing tendon and top spool</span><span><b>3</b> Check one joint in both directions</span></div>
 </section>
}

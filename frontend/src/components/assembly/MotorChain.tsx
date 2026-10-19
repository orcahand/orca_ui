import {GuideText} from './GuideEditing'
import {useEffect,useMemo,useState} from 'react'
import {Canvas,useFrame} from '@react-three/fiber'
import {OrbitControls,Html} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,fade,ease,framed} from './cadScene'
import {motorPieces,motorOwner,jointForMotor,jointName} from './driveMap'
import type {Build} from './buildContent'
function Chain({bundle,build,index,replay,face}:{bundle:Bundle;build:Build;index:number;replay:number;face:'palmar'|'dorsal'}){
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),motors=motorPieces(pieces),group=new THREE.Group()
  const selected=pieces.filter(p=>['Motor tower','Motor connector PCB','Dynamixel XC330 motor','Dynamixel XC430 wrist motor','Bottom spool','Ratchet','M2 hex nut','M2 × 4 socket screw'].includes(p.part.label))
  selected.forEach(p=>group.add(p.object));const view=framed(group,build,330)
  return {pieces,selected,motors,view}
 },[bundle,build])
 const [started,setStarted]=useState(0)
 useEffect(()=>setStarted(performance.now()),[index,replay])
 useEffect(()=>{scene.view.rotation.y=face==='palmar'?2.65:-.4},[scene,face])
 useEffect(()=>()=>disposePieces(scene.pieces),[scene])
 useFrame(()=>{const t=ease((performance.now()-started)/850),active=17-index
  for(const p of scene.selected){const isMotor=p.part.label.includes('motor')&&!p.part.label.includes('connector'),owner=isMotor?[...scene.motors].find(([,m])=>m===p)?.[0]:motorOwner(p,scene.motors),fixed=['Motor tower','Motor connector PCB'].includes(p.part.label)
   p.object.visible=fixed||!!owner&&owner>=active
   fade(p,fixed?.28:owner===active?1:.48)
   p.object.position.set(0,0,!fixed&&owner===active?(1-t)*80*Math.sign(p.center.z||1):0)
  }
 })
 return <primitive object={scene.view}>{[...scene.motors].filter(([id,p])=>id>=17-index&&(id===1||(face==='palmar'?p.center.z<0:p.center.z>0))).map(([id,p])=><Html key={id} position={p.center.clone().add(scene.view.children[0].position).add(new THREE.Vector3(0,5,0)).toArray()} center className="assembly-cad-callout">{id}</Html>)}</primitive>
}
export function MotorChain({build}:{build:Build}){
 const [index,setIndex]=useState(0),[replay,setReplay]=useState(0),[playing,setPlaying]=useState(false),[face,setFace]=useState<'palmar'|'dorsal'>('palmar'),[loaded,setLoaded]=useState<Bundle|null>(null),[failed,setFailed]=useState(false)
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 useEffect(()=>{let live=true;setLoaded(null);setFailed(false);loadBundle(key).then(b=>{if(live)setLoaded(b)}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 useEffect(()=>{if(!playing)return;const timer=setTimeout(()=>{if(index===16)setPlaying(false);else setIndex(i=>i+1)},1400);return()=>clearTimeout(timer)},[playing,index])
 useEffect(()=>setFace(index<8?'palmar':'dorsal'),[index])
 const id=17-index,joint=jointForMotor(id,build)
 return <section className="assembly-motor-chain" aria-label="Install motors in descending ID order">
  <div className="assembly-row"><div><h3><GuideText variant field="prose/MotorChain.tsx/1014917182" text={["Motor ",String(id)," · ",String(joint?jointName(joint):'Wrist')].join('').trim()} label="Guide text"/></h3></div><button className="assembly-secondary" onClick={()=>{if(index===16)setIndex(0);setPlaying(!playing)}}>{playing?'Pause preview':'Preview the sequence'}</button></div>
  <p><GuideText variant field="prose/MotorChain.tsx/3b1bf5e6fd" text={[String(build.motor==='feetech'?'Switch power OFF, connect this motor, then power ON. ':'Connect this motor. '),"Wait until the configuration tool detects it before installing the next one."].join('').trim()} label="Guide text"/></p>
  {build.motor==='dynamixel'&&<div className="assembly-clip-tabs"><button aria-pressed={face==='palmar'} onClick={()=>setFace('palmar')}>Palm side</button><button aria-pressed={face==='dorsal'} onClick={()=>setFace('dorsal')}>Back side</button></div>}
  {build.motor==='dynamixel'&&loaded?<div className="assembly-motor-chain-canvas"><Canvas orthographic camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.4}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Chain bundle={loaded} build={build} index={index} replay={replay} face={face}/><OrbitControls enablePan={false}/></Canvas></div>:build.motor==='dynamixel'?<p>{failed?'The motor model could not load. Reopen this step to retry; the connection order remains 17 → 1.':'Loading the motor assembly…'}</p>:<div className="assembly-motor-chain-reference"><img src="./assembly/media/feetech-5.jpg" alt="FeeTech motor column and direct cables"/></div>}
  <div className="assembly-motor-ids">{Array.from({length:17},(_,i)=><button key={i} aria-pressed={index===i} onClick={()=>{setPlaying(false);setIndex(i);setReplay(n=>n+1)}}>{17-i}</button>)}</div>
  <label className="assembly-motion-scrubber"><span>17 → 1</span><input aria-label="Motor installation order" type="range" min="0" max="16" value={index} onChange={e=>{setPlaying(false);setIndex(+e.target.value)}}/></label>
  <p className="assembly-motor-chain-cue"><GuideText variant field="prose/MotorChain.tsx/2a3a8b589e" text={String(index===16?'Link the last spool motor to the wrist motor. Wait for “All motors configured”, then turn board power off and fit both top and both bottom cable covers.':index%4===3?(id===10?'Palm-side columns complete. Link motor 10 to motor 9 across the top, then continue on the back side.':id===2?'All sixteen spool motors are installed. Connect the wrist motor last.':`Column complete. Link motor ${id} to motor ${id-1} at the bottom using a 30–50 mm cable. Keep the cable clear of the motor seats.`):`${index%4+1} of 4 in this column. ${build.motor==='dynamixel'?'Seat the motor on its connector PCB.':'Use the short direct motor cable.'}`)} label="Guide text"/></p>
 </section>
}

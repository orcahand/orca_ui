import {GuideText} from './GuideEditing'
import {useEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {motorCheckScene} from './motorCheckScene'
import {illustratedJointRange,rangeAngle,fitIllustratedRange} from './illustratedJointRange'
import {testJoint} from './jointTestControl'
import {motorId} from './driveMap'
import type {Build} from './buildContent'
const TYPES={
 PIP:{segment:'DP',color:'#d68d28',name:'Proximal interphalangeal',copy:'The outer finger hinge, between DP and PP. ORCA control names end in _pip.'},
 DIP:{segment:'DP',color:'#d68d28',name:'Thumb outer hinge',copy:'ORCA calls this thumb_dip. It is the thumb’s IP hinge, between DP and PP; the other four fingers use PIP.'},
 MCP:{segment:'PP',color:'#2c99af',name:'Metacarpophalangeal',copy:'The bending knuckle between PP and AP. ORCA control names end in _mcp.'},
 ABD:{segment:'AP',color:'#9263c4',name:'Abduction / adduction axis',copy:'ABD is ORCA’s name for side-to-side movement, not a separate anatomical joint name. The AP pivots at the hand body (at TP for the thumb). Control names end in _abd.'},
 CMC:{segment:'TP',color:'#cb6879',name:'Carpometacarpal',copy:'The thumb-base hinge, between TP and the carpals. ORCA calls it thumb_cmc.'},
 Wrist:{segment:'',color:'#32896e',name:'Wrist flexion / extension',copy:'The hand turns relative to the wrist frame on the carpal bearings. ORCA calls this joint wrist.'},
}
type JointType=keyof typeof TYPES
function JointModel({bundle,build,id,phase,color,kind,reverse}:{bundle:Bundle;build:Build;id:number;phase:number;color:string;kind:JointType;reverse:boolean}){
 const invalidate=useThree(s=>s.invalidate),size=useThree(s=>s.size),scene=useMemo(()=>{const scene=motorCheckScene(bundle,build,id,'hand',color);fitIllustratedRange(scene,illustratedJointRange(build,testJoint(id,build),scene.axis));return scene},[bundle,build,id,color])
 const range=useMemo(()=>illustratedJointRange(build,testJoint(id,build),scene.axis),[build,id,scene])
 useEffect(()=>()=>scene.dispose(),[scene])
 useEffect(()=>{const travel=(1-Math.cos(phase*Math.PI))/2;scene.setAngle(rangeAngle(range,reverse?1-travel:travel,kind==='ABD'?scene.spreadSign:scene.sign));invalidate()},[phase,reverse,kind,scene,range,invalidate])
 return <group scale={Math.min(1,(size.width-30)/430)}><primitive object={scene.view}/></group>
}
export function JointLesson({build}:{build:Build}){
 const [finger,setFinger]=useState('I'),[kind,setKind]=useState<JointType>('PIP'),[reverse,setReverse]=useState(false),[phase,setPhase]=useState(0),[playing,setPlaying]=useState(false),[loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`,type=TYPES[kind],id=kind==='Wrist'?1:motorId(`${finger}-${type.segment}`,build)
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 useEffect(()=>{setPhase(0);setPlaying(false)},[finger,kind])
 useEffect(()=>{if(!playing)return;let frame=0,last=0;const tick=(t:number)=>{if(last)setPhase(p=>Math.min(1,p+(t-last)/2400));last=t;frame=requestAnimationFrame(tick)};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[playing])
 useEffect(()=>{if(phase===1)setPlaying(false)},[phase])
 const movements=kind==='ABD'?['Abduction (spread away)','Adduction (bring back)']:['Flexion (bend)','Extension (straighten)']
 function chooseFinger(next:string){setFinger(next);if(kind==='CMC'&&next!=='T')setKind('MCP');if(kind==='DIP'&&next!=='T')setKind('PIP');if(kind==='PIP'&&next==='T')setKind('DIP')}
 return <section className="assembly-joint-lesson"><div className="assembly-row"><div><span className="assembly-eyebrow">JOINTS & MOVEMENTS</span><h3><GuideText variant field="prose/JointLesson.tsx/1311f3c5d6" text={"Phalanges meet at joints."} label="Section heading"/></h3></div></div><p><GuideText variant field="prose/JointLesson.tsx/a4af9f1d45" text={"The colored ring marks the joint’s rotation axis. Choose a finger, joint and movement to see how they relate."} label="Guide text"/></p>
  <div className="assembly-clip-tabs">{Object.entries({I:'Index',M:'Middle',R:'Ring',P:'Pinky',T:'Thumb'}).map(([id,name])=><button key={id} aria-pressed={finger===id} onClick={()=>chooseFinger(id)}>{name}</button>)}</div>
  <div className="assembly-clip-tabs">{(Object.keys(TYPES) as JointType[]).filter(k=>!(k==='PIP'&&finger==='T')&&!(k==='DIP'&&finger!=='T')&&!(k==='CMC'&&finger!=='T')).map(k=><button key={k} aria-pressed={kind===k} onClick={()=>setKind(k)}><span style={{background:TYPES[k].color}}/>{k}</button>)}</div>
  <div className="assembly-joint-lesson-layout"><div className="assembly-joint-lesson-canvas">{loaded?.key===key?<Canvas key={`${key}-${id}`} orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}}><ambientLight intensity={1.4}/><hemisphereLight intensity={1.5}/><directionalLight position={[300,400,600]} intensity={3}/><JointModel bundle={loaded.bundle} build={build} id={id} phase={phase} color={type.color} kind={kind} reverse={reverse}/><OrbitControls enablePan minZoom={.6} maxZoom={3}/></Canvas>:<p>{failed?'The joint model could not load. Reopen the step to retry.':'Loading joints…'}</p>}</div><div><h3 style={{color:type.color}}><GuideText variant field="prose/JointLesson.tsx/4eb2b79322" text={[String(kind)," (",String(type.name),")"].join('').trim()} label="Guide text"/></h3><div className="assembly-clip-tabs">{movements.map((name,i)=><button key={name} aria-pressed={reverse===(i===1)} onClick={()=>{setReverse(i===1);setPhase(0);setPlaying(true)}}>{name}</button>)}</div><label className="assembly-motion-scrubber"><span>{movements[reverse?1:0]}</span><input aria-label="Joint movement progress" type="range" min="0" max="1000" value={Math.round(phase*1000)} onChange={e=>{setPlaying(false);setPhase(+e.target.value/1000)}}/></label><p className="assembly-muted"><GuideText variant field="prose/JointLesson.tsx/31a230db0c" text={"Drag to rotate. Scroll or pinch to zoom. The animation covers the full range in the hand model. On a loose assembly, move gently without forcing the stops."} label="Guide text"/></p>{kind==='ABD'&&<p><GuideText variant field="prose/JointLesson.tsx/53590b5914" text={["In tendon labels, ","p"," means toward the pinky and ","t"," toward the thumb. These directions remain unambiguous when you turn the hand over."].join('').trim()} label="Guide text"/></p>}</div></div>
 </section>
}

import {GuideText} from './GuideEditing'
import {useEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {motorCheckName,MOTOR_CHECK_IDS} from './motorCheckScene'
import {liveHandPoseScene} from './liveHandPoseScene'
import {assemblyPose} from './livePoseTelemetry'
import {LiveJointTest} from './LiveJointTest'
import {useAppStore} from '../../state/appStore'
import {latest} from '../../state/streamStore'
import {useStreamFrame} from '../../hooks/useStreamFrame'
import type {Build} from './buildContent'
function Model({bundle,build,id,onReady}:{bundle:Bundle;build:Build;id:number;onReady:(ready:boolean)=>void}){
 const size=useThree(s=>s.size),invalidate=useThree(s=>s.invalidate),scene=useMemo(()=>liveHandPoseScene(bundle,build,id),[bundle,build,id])
 const info=useAppStore(s=>s.handInfo),control=useAppStore(s=>s.control),ws=useAppStore(s=>s.wsConnected),status=useAppStore(s=>s.status)
 const connected=ws&&!!status?.capabilities?.motors&&['connected','degraded'].includes(status.state)
 function update(){const pose=assemblyPose(build,info,control,connected,latest);onReady(!!pose&&scene.joints.every(j=>Number.isFinite(pose[j.name])));if(scene.setPose(pose))invalidate()}
 useEffect(()=>()=>scene.dispose(),[scene])
 useEffect(update,[scene,info,control,connected,build,invalidate,onReady])
 useStreamFrame(update)
 return <group scale={Math.min(1,(size.width-24)/430,(size.height-24)/350)}><primitive object={scene.view}/></group>
}
export function MotorCheck({build,checked,selected,onSelect,onCheck}:{build:Build;checked:number[];selected:number;onSelect:(id:number)=>void;onCheck:(id:number)=>void}){
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false),[ready,setReady]=useState(false)
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`,id=MOTOR_CHECK_IDS.includes(selected)?selected:1
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 const preview=<div className="assembly-motor-check-canvas hand" aria-label={`${motorCheckName(id,build)} movement`}>{loaded?.key===key?<Canvas key={`${key}-${id}`} orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}}><ambientLight intensity={1.2}/><hemisphereLight intensity={1.5}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Model bundle={loaded.bundle} build={build} id={id} onReady={setReady}/><OrbitControls enablePan={false} minZoom={.7} maxZoom={2}/></Canvas>:<p role="status">{failed?'Unable to load the preview. Close and reopen this step to retry.':'Loading your hand…'}</p>}</div>
 return <section className="assembly-motor-check" aria-label="Motor to joint verification">
  <div className="assembly-row"><div><span className="assembly-eyebrow">ONE MOTOR (ONE JOINT)</span><h3><GuideText variant field="prose/MotorCheck.tsx/8231080a38" text={["Motor ",String(id)," → ",String(motorCheckName(id,build))].join('').trim()} label="Guide text"/></h3></div><span>{checked.length} / 17 checked</span></div>
  <div className="assembly-motor-check-selectors">{MOTOR_CHECK_IDS.map(n=><button key={n} aria-pressed={n===id} onClick={()=>onSelect(n)}><span>{checked.includes(n)?'✓ ':''}{String(n).padStart(2,'0')}</span>{motorCheckName(n,build)}</button>)}</div>
  <div className="assembly-live-model"><h4><GuideText variant field="prose/MotorCheck.tsx/0839d6825b" text={String(motorCheckName(id,build))} label="Section heading"/></h4>{preview}<p role="status">{ready?'Model follows the reported joint angles.':'Assembly reference. Waiting for valid joint telemetry.'}</p></div>
  <LiveJointTest key={`${key}-${id}`} build={build} id={id}/>
  {build.version==='full'&&<p className="assembly-note"><GuideText variant field="prose/MotorCheck.tsx/b460f152b5" text={"Full uses the Base mechanical reference; sensor parts are not represented."} label="Guide text"/></p>}
  {build.motor==='feetech'&&<p className="assembly-note"><GuideText variant field="prose/MotorCheck.tsx/acc49ecd8a" text={"Motor IDs follow the selected hand."} label="Guide text"/></p>}
  <label className="assembly-route-check"><input type="checkbox" checked={checked.includes(id)} onChange={()=>onCheck(id)}/><span>I checked motor {id}: {id===1?'the wrist moves freely in both directions.':`only the ${motorCheckName(id,build)} joint is driven, and both tendons run freely.`}</span></label>
  <button className="assembly-text-button" disabled={checked.length===17} onClick={()=>onSelect(MOTOR_CHECK_IDS.find(n=>n>id&&!checked.includes(n))??MOTOR_CHECK_IDS.find(n=>!checked.includes(n))??id)}>Next unchecked motor →</button>
 </section>
}

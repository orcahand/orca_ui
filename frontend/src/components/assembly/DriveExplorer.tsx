import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useFrame,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,fade,framed,TENDON_COLORS} from './cadScene'
import {JOINTS,jointName,jointTendons,motorId,motorPieces} from './driveMap'
import {WristOutletView} from './WristOutletView'
import {ChannelCurve} from './channelStrands'
import {handTendonPath} from './conduitPaths'
import {TENDONS} from './guide'
import type {Build} from './buildContent'
function Trace({bundle,build,joint,tendon,wristOnly}:{bundle:Bundle;build:Build;joint:string;tendon:number;wristOnly:boolean}){
 const bead=useRef<THREE.Mesh>(null)
 const container=useRef<THREE.Group>(null),size=useThree(s=>s.size)
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),group=new THREE.Group(),label=jointName(joint),segment=pieces.find(p=>p.part.label===label)!,motor=motorPieces(pieces).get(motorId(joint,build))!
  const excluded=['Hull cover','Rear hull cover','Side plate','Fan cover · two fans','Arm mounting adapter (optional)','Arm mounting rod (optional)','Tendon paths']
  pieces.filter(p=>!excluded.includes(p.part.label)&&(!wristOnly||!p.part.areas.Tower)).forEach(p=>{group.add(p.object);fade(p,p===segment||!wristOnly&&p===motor?1:.12,p===segment?'#28889d':!wristOnly&&p===motor?'#dba835':undefined)})
  const curve=new ChannelCurve(handTendonPath(build,tendon)),tube=new THREE.Mesh(new THREE.TubeGeometry(curve,1800,tendon>=8&&tendon<16?.14:.18,10,false),new THREE.MeshBasicMaterial({color:TENDON_COLORS[tendon%8]}));group.add(tube)
  const view=framed(group,build,390),offset=group.position.clone()
  return {pieces,view,curve,tube,offset,segment,motor}
 },[bundle,build,joint,tendon,wristOnly])
 useLayoutEffect(()=>{
  const wrapper=container.current!
  wrapper.scale.setScalar(1);wrapper.position.set(0,0,0)
  wrapper.updateMatrixWorld(true)
  const bounds=new THREE.Box3().setFromObject(scene.view),extent=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3())
  const scale=Math.max(.01,Math.min(1,(size.width-32)/extent.x,(size.height-32)/extent.y))
  wrapper.scale.setScalar(scale);wrapper.position.copy(center).multiplyScalar(-scale)
 },[scene,size.width,size.height])
 useEffect(()=>()=>{disposePieces(scene.pieces);scene.tube.geometry.dispose();(scene.tube.material as THREE.Material).dispose()},[scene])
 useFrame(({clock})=>{bead.current?.position.copy(scene.curve.getPoint((clock.elapsedTime*.23)%1)).add(scene.offset)})
 return <group ref={container}><primitive object={scene.view}>
  <mesh ref={bead}><sphereGeometry args={[.8,12,12]}/><meshBasicMaterial color="#fff"/></mesh>
 </primitive></group>
}
export function DriveExplorer({build,checked,onCheck,stage='wrist'}:{build:Build;checked:number[];onCheck:(index:number)=>void;stage?:'wrist'|'bottom'|'top'}){
 const wristOnly=stage==='wrist'
 const [joint,setJoint]=useState('I-DP'),[selected,setSelected]=useState(0),[loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`,pair=jointTendons(joint),tendon=pair[selected]?.index??pair[0].index
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 return <section className="assembly-drive-explorer" aria-label={wristOnly?'Check the hand-to-wrist tendon paths':'Explore joint, tendon and motor connections'}>
  <div className="assembly-row"><h3>{wristOnly?'Follow each tendon through the wrist':'One joint · two tendons · one motor'}</h3><span>{wristOnly?`${checked.length} / 32 tendons checked`:`${JOINTS.filter(j=>jointTendons(j).every(p=>checked.includes(p.index))).length} / 16 ${stage==='bottom'?'bottom spools':'tendon pairs'} checked`}</span></div>
  <div className="assembly-joint-selectors">{['T','I','M','R','P'].map(f=><div className="assembly-joint-group" key={f}><h4>{({T:'Thumb',I:'Index',M:'Middle',R:'Ring',P:'Pinky'} as Record<string,string>)[f]}</h4>{['DP','PP','AP',...(f==='T'?['TP']:[])].map(segment=>{const j=`${f}-${segment}`;return <button key={j} aria-label={jointName(j)} aria-pressed={joint===j} onClick={()=>{setJoint(j);setSelected(0)}}>{segment}</button>})}</div>)}</div>
  <div className="assembly-drive-controls"><strong>{jointName(joint)}{!wristOnly?` · Motor ${motorId(joint,build)}`:''}</strong>
   <div className="assembly-clip-tabs">{pair.map((p,i)=><button key={p.index} aria-pressed={i===selected} onClick={()=>setSelected(i)}>{p.index+1} · {p.name}</button>)}</div>
   <p>{stage==='bottom'?'Identify tendon '+(tendon+1)+' before anchoring it.':stage==='top'?'With power off, turn the motor gently by hand to check tendon '+(tendon+1)+'.':'Gently pull tendon '+(tendon+1)+'.'} {TENDONS[tendon].endsWith('flex')?'The joint should bend toward the palm.':TENDONS[tendon].endsWith('ext')?'The joint should straighten away from the palm.':`The base should move toward the ${TENDONS[tendon].endsWith('-p')?'pinky':'thumb'}.`} {stage==='top'?'Turn the other way to check its partner.':'Leave its partner slack.'}</p>
  </div><div className="assembly-drive-layout">
   {loaded?.key===key?<div className="assembly-drive-canvas"><Canvas orthographic camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.4}/><directionalLight position={[300,500,700]} intensity={3}/><Trace bundle={loaded.bundle} build={build} joint={joint} tendon={tendon} wristOnly={wristOnly||build.motor==='feetech'}/><OrbitControls enablePan minZoom={.6} maxZoom={4}/></Canvas></div>:<p>{failed?'The model could not load. Use the numbered channel view.':'Loading the tendon view…'}</p>}
   <WristOutletView build={build} selected={tendon}/>
  </div><div className="assembly-drive-checks">
   <label className="assembly-route-check"><input type="checkbox" checked={pair.every(p=>checked.includes(p.index))} onChange={()=>{const complete=pair.every(p=>checked.includes(p.index));pair.filter(p=>complete||!checked.includes(p.index)).forEach(p=>onCheck(p.index))}}/><span>{stage==='bottom'?`${jointName(joint)}: the bottom tendon is anchored with its tail tucked in, it winds on the spool, and the opposite tendon is kept free for the top spool.`:stage==='top'?`${jointName(joint)}: both spools are fitted and turning motor ${motorId(joint,build)} gently by hand moves only this joint in both directions.`:`Both ${jointName(joint)} tendons move this joint correctly and freely.`}</span></label>
   <button className="assembly-text-button" onClick={()=>{setJoint(JOINTS[(JOINTS.indexOf(joint)+1)%JOINTS.length]);setSelected(0)}}>Next joint →</button>
  </div>
 </section>
}

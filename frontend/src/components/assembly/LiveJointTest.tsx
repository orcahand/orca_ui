import {useEffect,useRef,useState} from 'react'
import {api} from '../../api/rest'
import {useAppStore} from '../../state/appStore'
import {latest} from '../../state/streamStore'
import {useStreamFrame} from '../../hooks/useStreamFrame'
import {liveTestBlock,testJoint,testTarget} from './jointTestControl'
import type {Build} from './buildContent'

export function LiveJointTest({build,id}:{build:Build;id:number}){
 const info=useAppStore(s=>s.handInfo),status=useAppStore(s=>s.status),control=useAppStore(s=>s.control),ws=useAppStore(s=>s.wsConnected)
 const name=testJoint(id,build),joint=info?.joints.find(j=>j.id===name),rom=joint?.rom
 const [armed,setArmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[offset,setOffset]=useState(0),[position,setPosition]=useState<number|null>(null)
 const center=useRef<number|null>(null),enabled=useRef(false),pending=useRef<number|null>(null),sending=useRef(false),generation=useRef(0),mounted=useRef(true)
 const block=liveTestBlock(build,info,status,control,ws)
 const unavailable=block??(!joint||Math.abs(joint.motor_id??0)!==id?'The connected motor mapping does not match this joint.':null)
 const readPose=()=>joint?.encoder_backed?latest.joints.measured[name]:control?.effective_pose_source==='target'?latest.joints.target[name]:latest.joints.estimate[name]
 const eligible=()=>{const s=useAppStore.getState();return !liveTestBlock(build,s.handInfo,s.status,s.control,s.wsConnected)&&s.control?.torque_enabled&&Math.abs(s.handInfo?.joints.find(j=>j.id===name)?.motor_id??0)===id}
 const report=(e:unknown)=>{if(mounted.current)setError(e instanceof Error?e.message:String(e))}
 async function release(){
  const owned=enabled.current;enabled.current=false;pending.current=null;generation.current++
  if(mounted.current){setArmed(false);setOffset(0)}
  if(owned&&useAppStore.getState().control?.control_source==='manual')try{await api.torqueDisable()}catch(e){report(e)}
 }
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;void release()}},[])
 useEffect(()=>{void release();center.current=null;setOffset(0);setPosition(null)},[name,build.side,build.version])
 useEffect(()=>{if(armed&&(unavailable||!control?.torque_enabled))void release()},[armed,unavailable,control?.torque_enabled])
 useStreamFrame(()=>{
  const angle=readPose()
  if(!Number.isFinite(angle))return
  setPosition(p=>p!==null&&Math.abs(p-angle)<.05?p:angle)
 })
 async function enable(){
  if(unavailable||busy)return
  setBusy(true);setError('');const run=++generation.current
  try{
   const {seed}=await api.torqueEnable()
   if(!mounted.current||run!==generation.current){if(useAppStore.getState().control?.control_source==='manual')await api.torqueDisable();return}
   const angle=seed[name]
   if(!rom||testTarget(angle,0,rom)===null){await api.torqueDisable();throw new Error('A valid current joint angle is required. Check calibration in Setup.')}
   const state=useAppStore.getState()
   if(liveTestBlock(build,state.handInfo,state.status,state.control,state.wsConnected)){if(state.control?.control_source==='manual')await api.torqueDisable();throw new Error('The hand state changed. Recheck the connection before enabling the test.')}
   if(state.control)state.setControl({...state.control,torque_enabled:true})
   center.current=angle;enabled.current=true;setOffset(0);setPosition(angle);setArmed(true)
  }catch(e){report(e)}finally{if(mounted.current)setBusy(false)}
 }
 async function flush(){
  if(sending.current)return
  sending.current=true;const run=generation.current
  try{
   while(pending.current!==null&&enabled.current&&run===generation.current&&eligible()){
    const target=pending.current;pending.current=null;await api.jointsTarget({[name]:target})
   }
  }catch(e){pending.current=null;report(e);await release()}finally{sending.current=false;if(pending.current!==null&&enabled.current&&eligible())void flush()}
 }
 function slide(value:number){
  if(!enabled.current||!eligible()||center.current===null||!rom)return
  const target=testTarget(center.current,value,rom);if(target===null)return
  setOffset(target-center.current);pending.current=target;void flush()
 }
 return <section className="assembly-live-test" aria-label="Connected hand test">
  <div className="assembly-row"><h3>{info?.mock?'Mock hand test':'Test the connected hand'}</h3>{armed?<button className="assembly-secondary" onClick={()=>void release()}>Release hand</button>:<button className="assembly-primary" disabled={!!unavailable||busy} onClick={()=>void enable()}>{busy?'Preparing test…':'Enable joint test'}</button>}</div>
  {unavailable&&<p role="status">{unavailable}</p>}
  {!status?.capabilities?.motors&&<button className="assembly-secondary" disabled={!ws||busy} onClick={async()=>{setBusy(true);setError('');try{await api.reconnect()}catch(e){report(e)}finally{if(mounted.current)setBusy(false)}}}>Connect hand</button>}
  {!unavailable&&!armed&&<p>Support the hand and clear its travel. Enable the test to hold its current position.</p>}
  <label className="assembly-motion-scrubber"><span>−10°</span><input aria-label="Move connected joint" type="range" min="-10" max="10" step="0.1" disabled={!armed||!!unavailable} value={offset} onChange={e=>slide(+e.target.value)}/><span>+10°</span></label>
  <p>{offset>0?'+':''}{offset.toFixed(1)}° from the starting position{position!==null?` · ${joint?.encoder_backed?'Measured':control?.effective_pose_source==='target'?'Commanded':'Motor estimate'} ${position.toFixed(1)}°`:''}</p>
  {armed&&<p>Move gently in both directions and check the physical joint. Travel is limited to its calibrated range.</p>}
  {error&&<p role="alert">{error}</p>}
 </section>
}

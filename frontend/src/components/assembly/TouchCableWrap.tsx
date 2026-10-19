import {GuideText} from './GuideEditing'
import {useEffect,useLayoutEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {touchCableScene} from './touchCableScene'
function Cable({progress,close}:{progress:number;close:boolean}){
 const model=useMemo(()=>touchCableScene(),[]),{camera,size,invalidate}=useThree()
 useEffect(()=>()=>model.dispose(),[model])
 useLayoutEffect(()=>{
  model.update(progress)
  model.group.position.x=close?20:0
  camera.zoom=Math.min((size.width-40)/(close?43:145),(size.height-40)/(close?18:42))
  camera.updateProjectionMatrix();invalidate()
 },[model,progress,close,camera,size,invalidate])
 return <primitive object={model.group}/>
}
export function TouchCableWrap(){
 const [progress,setProgress]=useState(1),[playing,setPlaying]=useState(false),[close,setClose]=useState(false),[reference,setReference]=useState(false)
 useEffect(()=>{
  if(!playing)return
  let frame=0,previous=0
  const tick=(now:number)=>{if(previous)setProgress(p=>Math.min(1,p+(now-previous)/6500));previous=now;frame=requestAnimationFrame(tick)}
  frame=requestAnimationFrame(tick)
  return()=>cancelAnimationFrame(frame)
 },[playing])
 useEffect(()=>{if(progress>=1)setPlaying(false)},[progress])
 return <section className="assembly-cable-wrap" aria-label="130 mm cable wrapping model">
  <div className="assembly-row"><div></div><button className="assembly-secondary" onClick={()=>{if(progress>=1)setProgress(0);setPlaying(!playing)}}>{playing?'Pause wrapping':'Play wrapping'}</button></div>
  <div className="assembly-clip-tabs"><button aria-pressed={!close} onClick={()=>setClose(false)}>Whole cable</button><button aria-pressed={close} onClick={()=>setClose(true)}>Wrap close-up</button></div>
  <div className="assembly-cable-model" role="img" aria-label="Rotatable 130 millimetre cable with a 30 millimetre copper wrap and 70 millimetres from the wrap end to the right connector">
   <Canvas orthographic frameloop="demand" camera={{position:[0,0,180],near:.1,far:1000}} dpr={[1,2]}>
    <color attach="background" args={['#e8edef']}/><ambientLight intensity={1.6}/><directionalLight position={[20,70,90]} intensity={3}/><directionalLight position={[-40,-50,30]} intensity={1.4}/>
    <Cable progress={progress} close={close}/><OrbitControls key={String(close)} enablePan={false} enableZoom={false}/>
   </Canvas>
  </div>
  <svg className="assembly-cable-measurements" viewBox="0 0 780 115" role="img" aria-label="Reference layout: about 30 mm of copper wrapping, then about 70 mm to the right connector, tolerance plus or minus 5 mm">
   <path d="M35 20 H745" stroke="currentColor" strokeWidth="4"/><path d="M199 20 H363" stroke="#c88951" strokeWidth="9"/>
   <path d="M199 32 V74 M363 32 V74 M745 32 V74 M199 62 H745 M209 57 L199 62 L209 67 M353 57 L363 62 L353 67 M373 57 L363 62 L373 67 M735 57 L745 62 L735 67" fill="none" stroke="currentColor" strokeWidth="1.5"/>
   <text x="281" y="98" textAnchor="middle">≈30 mm wrap</text><text x="554" y="98" textAnchor="middle">≈70 mm to right connector (±5 mm)</text>
  </svg>
  <p className="assembly-cable-mobile-measurements"><GuideText variant field="prose/TouchCableWrap.tsx/3ea451630e" text={["Wrap: ","≈30 mm","\n","To right connector: ","≈70 mm (±5 mm)"].join('').trim()} label="Guide text"/></p>
  <label className="assembly-motion-scrubber"><span>Wrapping progress</span><input aria-label="Cable wrapping progress" type="range" min="0" max="100" value={Math.round(progress*100)} onChange={e=>{setPlaying(false);setProgress(Number(e.target.value)/100)}}/></label>
  <p><GuideText variant field="prose/TouchCableWrap.tsx/4c5f9149cf" text={["Keep about ","1 mm between turns",". Secure both ends with the clove hitch shown above, then trim the wire tails below 2 mm."].join('').trim()} label="Guide text"/></p>
  <button className="assembly-text-button" aria-expanded={reference} onClick={()=>setReference(!reference)}>{reference?'Hide reference photo':'Show reference photo'}</button>
  {reference&&<figure className="assembly-cable-reference"><img src="./assembly/touch/wrap-short.png" alt="Original cable photo with a 3 cm copper wrap and 7 cm from its end to the right connector"/><figcaption><GuideText variant field="prose/TouchCableWrap.tsx/5aeb56ea7e" text={"Match the connector orientation shown."} label="Guide text"/></figcaption></figure>}
 </section>
}

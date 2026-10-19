import {GuideText} from './GuideEditing'
import {useEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {cadDetailSpec,cadDetailScene,THUMB_PARTS} from './cadDetails'
import {AssemblyComparison} from './AssemblyComparison'
import type {Build} from './buildContent'
function Model({bundle,build,step,amount,highlight}:{bundle:Bundle;build:Build;step:string;amount:number;highlight:string}){
 const size=useThree(s=>s.size),invalidate=useThree(s=>s.invalidate),scene=useMemo(()=>cadDetailScene(bundle,build,step),[bundle,build,step])
 useEffect(()=>()=>scene.dispose(),[scene]);useEffect(()=>{scene.update(amount,highlight);invalidate()},[scene,amount,highlight,invalidate]);return <group scale={Math.min(1,(size.width-24)/530,(size.height-24)/340)}><primitive object={scene.view}/></group>
}
export function CadDetail({build,step}:{build:Build;step:string}){
 const spec=cadDetailSpec(build,step),key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 const startAmount=useRef(1)
 const [highlight,setHighlight]=useState('')
 useEffect(()=>setHighlight(''),[step,key])
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false),[amount,setAmount]=useState(step==='p139'?0:1),[playing,setPlaying]=useState(false)
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 useEffect(()=>{if(!playing)return;const from=startAmount.current;let frame=0,start=0;const tick=(now:number)=>{if(!start)start=now;const p=Math.min(1,(now-start)/(4000*from));setAmount(from*(1-p*p*(3-2*p)));if(p<1)frame=requestAnimationFrame(tick);else setPlaying(false)};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[playing])

 const renderModel=()=><><div className="assembly-cad-detail-canvas">{loaded?.key===key?<Canvas orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}}><ambientLight intensity={1.3}/><hemisphereLight intensity={1.5}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Model bundle={loaded.bundle} build={build} step={step} amount={amount} highlight={step==='thumb-parts'?highlight:''}/><OrbitControls enablePan={false} minZoom={.7} maxZoom={2}/></Canvas>:<p>{failed?'Unable to load the assembly. Reopen this step to retry.':'Loading the assembly…'}</p>}</div>
  {step==='thumb-parts'&&<><div className="assembly-thumb-legend" role="group" aria-label="Identify thumb parts">{THUMB_PARTS.map(part=><button key={part.label} type="button" aria-pressed={highlight===part.label} onClick={()=>setHighlight(highlight===part.label?'':part.label)}><span className="assembly-thumb-swatch" style={{backgroundColor:part.color}} aria-hidden="true"/><span><strong>{part.short}</strong><span>{part.name}</span></span></button>)}</div><p className="assembly-muted">Select a label to highlight its part. Select it again to show all four.</p></>}
 </>
 return <section className="assembly-cad-detail" data-contrast={build.version==='base'&&['pp-ready','finishing-pp','thumb-pp-ready','thumb-skins','thumb-test','p73','p139'].includes(step)} aria-label={spec.title}>
  <div className="assembly-row"><div><h3><GuideText variant field="prose/CadDetail.tsx/8ec6bab45a" text={String(spec.title)} label="Section heading"/></h3></div>{step!=='p139'&&spec.moving.length>0&&<button className="assembly-secondary" aria-label={playing?'Pause fitting':'Play fitting'} onClick={()=>{startAmount.current=amount===0?1:amount;setPlaying(!playing)}}>{playing?'Ⅱ':'▶'}</button>}</div>
  {renderModel()}
  <AssemblyComparison step={step} build={build} model={renderModel}/>
  {step!=='p139'&&spec.moving.length>0&&<><label className="assembly-motion-scrubber"><span>Separated</span><input aria-label="Assembly fitting progress" type="range" min="0" max="1000" value={Math.round((1-amount)*1000)} onChange={e=>{setPlaying(false);setAmount(1-+e.target.value/1000)}}/><span>Fitted</span></label></>}
  {step==='p139'&&<p><GuideText variant field="prose/CadDetail.tsx/148a516204" text={String(spec.caption)} label="Guide text"/></p>}<small className="assembly-muted">Drag to rotate; scroll to zoom.{step!=='p139'?' The view shows fitting locations; follow the written order.':''}{build.version==='full'?' Full uses the Base mechanical reference.':''}{build.motor==='feetech'?' The wrist and tower shown use Dynamixel geometry.':''}</small>
 </section>
}

import {useEffect,useLayoutEffect,useMemo,useState} from 'react'
import {Canvas,useThree,type ThreeEvent} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import type {Build} from './buildContent'
import {touchScrewScene,TOUCH_FINGERS,SCREW_COLORS,type TouchFinger} from './touchScrewScene'
function ScrewModel({bundle,build,finger,length,exploded,seeThrough,onSelect}:{bundle:Bundle;build:Build;finger:TouchFinger;length:number;exploded:number;seeThrough:boolean;onSelect:(length:number)=>void}){
 const model=useMemo(()=>touchScrewScene(bundle,build,finger),[bundle,build,finger]),{size,invalidate}=useThree()
 useEffect(()=>()=>model.dispose(),[model])
 useLayoutEffect(()=>{
  model.update(length,exploded,seeThrough)
  model.view.scale.setScalar(Math.min((size.width-48)/model.size.x,(size.height-48)/model.size.y))
  invalidate()
 },[model,length,exploded,seeThrough,size,invalidate])
 const select=(event:ThreeEvent<MouseEvent>)=>{
  let object=event.object
  while(object.parent&&!object.userData.screwLength)object=object.parent
  if(object.userData.screwLength){event.stopPropagation();onSelect(object.userData.screwLength)}
 }
 return <primitive object={model.view} onClick={select}/>
}
export function TouchScrewGuide({build}:{build:Build}){
 const [finger,setFinger]=useState<TouchFinger>('Index'),[length,setLength]=useState(0),[exploded,setExploded]=useState(0),[seeThrough,setSeeThrough]=useState(false)
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
 const key=`touch-${build.side}-dynamixel`,tip=finger==='Thumb'?4:3,lower=finger==='Thumb'?6:4
 useEffect(()=>{let active=true;setFailed(false);loadBundle(key).then(bundle=>{if(active)setLoaded({key,bundle})}).catch(()=>{if(active)setFailed(true)});return()=>{active=false}},[key])
 return <section className="assembly-touch-screws" aria-label="Touch sensor screw positions">
  <div className="assembly-row"><div><span className="assembly-eyebrow">TOUCH SENSOR · FOUR SCREWS PER FINGER</span><h3>Match the screw to its hole</h3></div><span>{build.side==='left'?'Left':'Right'} hand</span></div>
  <div className="assembly-clip-tabs assembly-touch-fingers" aria-label="Choose finger">{TOUCH_FINGERS.map(name=><button key={name} aria-pressed={finger===name} onClick={()=>{setFinger(name);setLength(0)}}>{name}</button>)}</div>
  <div className="assembly-screw-key" aria-label="Highlight screw length">
   <button aria-pressed={length===0} onClick={()=>setLength(0)}>All four screws</button>
   {[{length:tip,location:'Tip pair'},{length:lower,location:'Lower pair'}].map(item=><button key={item.location} aria-pressed={length===item.length} onClick={()=>setLength(item.length)}><i style={{background:SCREW_COLORS[item.length]}}/>{item.location} · 2 × M1.4×{item.length}</button>)}
  </div>
  <div className="assembly-screw-model" aria-label={`${finger} sensor with four color-coded screw locations`}>
   {loaded?.key===key?<Canvas key={`${key}-${finger}`} orthographic frameloop="demand" camera={{position:[0,0,1000],near:.1,far:4000}} dpr={[1,2]}>
    <color attach="background" args={['#e8edef']}/><ambientLight intensity={1.4}/><hemisphereLight intensity={1.5}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/>
    <ScrewModel bundle={loaded.bundle} build={build} finger={finger} length={length} exploded={exploded} seeThrough={seeThrough} onSelect={setLength}/><OrbitControls enablePan={false} minZoom={.6} maxZoom={3}/>
   </Canvas>:<p>{failed?'The model could not load. Use the reference screw diagrams below.':'Loading the sensor screw positions…'}</p>}
  </div>
  <div className="assembly-screw-controls"><label><input type="checkbox" checked={seeThrough} onChange={e=>setSeeThrough(e.target.checked)}/> See screw shafts through the parts</label><label className="assembly-motion-scrubber"><span>Separate screws</span><input aria-label="Separate sensor screws" type="range" min="0" max="100" value={exploded*100} onChange={e=>setExploded(Number(e.target.value)/100)}/></label></div>
  <p aria-live="polite">{finger}: <strong>two M1.4×{tip} at the tip</strong> and <strong>two M1.4×{lower} in the lower holes</strong>. Tighten gently with a hand screwdriver.</p>
  <p className="assembly-muted">Click a screw or its length to highlight the matching pair. Drag to rotate; scroll or pinch to zoom. Colors match the reference diagrams. Screw shapes are simplified; their lengths and mounting positions are shown.</p>
  <details className="assembly-screw-reference" open={failed}><summary>Original screw diagrams</summary><div>{['fingers','thumb'].map(kind=><figure key={kind}><img src={`./assembly/touch/screws-${kind}.png`} alt={kind==='thumb'?'Thumb: blue M1.4×4 screws at the tip, orange M1.4×6 below':'Fingers: green M1.4×3 screws at the tips, blue M1.4×4 below'}/><figcaption>{kind==='thumb'?'Thumb':'Index, middle, ring and pinky'} · reference orientation</figcaption></figure>)}</div></details>
 </section>
}

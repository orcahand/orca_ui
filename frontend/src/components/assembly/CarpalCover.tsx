import {useEffect,useLayoutEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {STLLoader} from 'three/examples/jsm/loaders/STLLoader.js'
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js'
import type {BufferGeometry,Mesh} from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {carpalCoverScene} from './carpalCoverScene'
import {GuideText} from './GuideEditing'
import type {Build} from './buildContent'

function Model({bundle,geometry,body,build,progress}:{bundle:Bundle;geometry:BufferGeometry;body:BufferGeometry;build:Build;progress:number}){
 const scene=useMemo(()=>carpalCoverScene(bundle,build,geometry,body),[bundle,build,geometry,body]),{size,invalidate}=useThree()
 useEffect(()=>()=>scene.dispose(),[scene])
 useLayoutEffect(()=>{scene.update(progress);scene.view.scale.setScalar(Math.min((size.width-48)/scene.size.x,(size.height-48)/scene.size.y));invalidate()},[scene,progress,size,invalidate])
 return <primitive object={scene.view}/>
}
export function CarpalCover({build}:{build:Build}){
 const [loaded,setLoaded]=useState<{side:string;bundle:Bundle;geometry:BufferGeometry;body:BufferGeometry}|null>(null),[failed,setFailed]=useState(false),[progress,setProgress]=useState(0)
 useEffect(()=>{
  let live=true,geometry:BufferGeometry|undefined,body:BufferGeometry|undefined;setFailed(false);setProgress(0)
  const cover=new STLLoader().loadAsync(`./assembly/supplies/carpal-cover-${build.side}.stl`).then(g=>{geometry=g;if(!live)g.dispose();return g})
  const carpals=new GLTFLoader().loadAsync(`./assembly/details/touch-carpals-${build.side}.glb`).then(gltf=>{const mesh=gltf.scene.getObjectByName('Touch_carpals')??gltf.scene.children[0];body=(mesh as Mesh).geometry;const materials=(mesh as Mesh).material;for(const m of Array.isArray(materials)?materials:[materials])m.dispose();if(!live)body.dispose();return body})
  Promise.all([loadBundle(`touch-${build.side}-dynamixel`),cover,carpals]).then(([bundle,geometry,body])=>{if(live)setLoaded({side:build.side,bundle,geometry,body})}).catch(()=>{if(live)setFailed(true)})
  return()=>{live=false;geometry?.dispose();body?.dispose()}
 },[build.side])
 const stage=progress<.6?'Seat the cover':progress<1?'Fit the four screws':'Cover secured'
 return <section className="assembly-carpal-cover" aria-label="Carpal cover fitting model">
  <h3><GuideText field="carpal-cover/model-title" text="Fit the carpal cover and screws" label="Section heading"/></h3>
  <p className="assembly-muted">{build.side==='left'?'Left':'Right'} hand. Four self-tapping M1.4×6 screws.</p>
  <div className="assembly-carpal-cover-canvas">
   {loaded?.side===build.side?<Canvas key={build.side} orthographic frameloop="demand" camera={{position:[0,0,1000],near:.1,far:4000}} dpr={[1,2]}>
    <color attach="background" args={['#e8edef']}/><ambientLight intensity={1.3}/><hemisphereLight intensity={1.4}/><directionalLight position={[200,400,600]} intensity={3}/><directionalLight position={[-300,0,-300]} intensity={1.5}/>
    <Model bundle={loaded.bundle} geometry={loaded.geometry} body={loaded.body} build={build} progress={progress}/><OrbitControls enablePan={false} minZoom={.7} maxZoom={3}/>
   </Canvas>:<p>{failed?'Unable to load the cover model. Reopen this step to retry.':'Loading the carpal cover…'}</p>}
  </div>
  <label className="assembly-motion-scrubber"><span>Separated</span><input aria-label="Carpal cover fitting progress" type="range" min="0" max="100" value={Math.round(progress*100)} onChange={e=>setProgress(Number(e.target.value)/100)}/><span>Secured</span></label>
  <p aria-live="polite">{stage}</p>
  <small className="assembly-muted">The cover is highlighted in blue. Drag the slider to seat the cover, then insert the screws. Drag the model to rotate; scroll or pinch to zoom.</small>
 </section>
}

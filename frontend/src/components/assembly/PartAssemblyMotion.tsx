import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react'
import * as THREE from 'three'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {assemblyScene} from './assemblyScene'
import type {Build} from './buildContent'
function Parts({bundle,build,step,position,tendon,inspection,channels,zoom}:{bundle:Bundle;build:Build;step:string;position:number;tendon:number;inspection?:'rotation'|'axial';channels?:boolean;zoom:number}){
 const size=useThree(s=>s.size),invalidate=useThree(s=>s.invalidate),scene=useMemo(()=>assemblyScene(bundle,build,step),[bundle,build,step])
 const container=useRef<THREE.Group>(null)
 useEffect(()=>()=>scene.dispose(),[scene])
 useLayoutEffect(()=>{
  const wrapper=container.current!
  wrapper.scale.setScalar(1);wrapper.position.set(0,0,0)
  scene.update(position,tendon,inspection,channels)
  wrapper.updateMatrixWorld(true)
  if(['p33','p42','p46','p54','p62','p64','p68','p89','p123','p126'].includes(step)){
   const bounds=new THREE.Box3().setFromObject(scene.view),extent=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3())
   const scale=Math.max(.01,Math.min(1,(size.width-32)/(extent.x*zoom),(size.height-32)/(extent.y*zoom)))
   wrapper.scale.setScalar(scale);wrapper.position.copy(center).multiplyScalar(-scale)
  }else wrapper.scale.setScalar(Math.min(1,(size.width-20)/(step==='p99'?580:400)))
  invalidate()
 },[scene,position,tendon,inspection,channels,invalidate,size.width,size.height,step,zoom])
 return <group ref={container}><primitive object={scene.view}/></group>
}
export function PartAssemblyMotion({build,step,position,tendon=0,inspection,channels,zoom=1}:{build:Build;step:string;position:number;tendon?:number;inspection?:'rotation'|'axial';channels?:boolean;zoom?:number}){
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false),key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 return <div className="assembly-joint-motion" aria-label="CAD assembly with tendons, bearings and fasteners">
  {loaded?.key===key?<Canvas orthographic frameloop="demand" camera={{position:[0,0,1000],zoom,near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.3}/><hemisphereLight intensity={1.5}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Parts bundle={loaded.bundle} build={build} step={step} position={position} tendon={tendon} inspection={inspection} channels={channels} zoom={zoom}/><OrbitControls enablePan minZoom={.6} maxZoom={4}/></Canvas>:<p>{failed?'The model could not load. Use the routing photographs.':'Loading the assembly…'}</p>}
 </div>
}

import {useEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {assemblyScene} from './assemblyScene'
import type {Build} from './buildContent'
function Parts({bundle,build,step,position,tendon,inspection,channels}:{bundle:Bundle;build:Build;step:string;position:number;tendon:number;inspection?:'rotation'|'axial';channels?:boolean}){
 const size=useThree(s=>s.size),invalidate=useThree(s=>s.invalidate),scene=useMemo(()=>assemblyScene(bundle,build,step),[bundle,build,step])
 useEffect(()=>()=>scene.dispose(),[scene])
 useEffect(()=>{scene.update(position,tendon,inspection,channels);invalidate()},[scene,position,tendon,inspection,channels,invalidate])
 return <group scale={Math.min(1,(size.width-20)/(['p99','p123','p126'].includes(step)?580:400))}><primitive object={scene.view}/></group>
}
export function PartAssemblyMotion({build,step,position,tendon=0,inspection,channels,zoom=1}:{build:Build;step:string;position:number;tendon?:number;inspection?:'rotation'|'axial';channels?:boolean;zoom?:number}){
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false),key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
 return <div className="assembly-joint-motion" aria-label="CAD assembly with tendons, bearings and fasteners">
  {loaded?.key===key?<Canvas orthographic frameloop="demand" camera={{position:[0,0,1000],zoom,near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.3}/><hemisphereLight intensity={1.5}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Parts bundle={loaded.bundle} build={build} step={step} position={position} tendon={tendon} inspection={inspection} channels={channels}/><OrbitControls enablePan minZoom={.6} maxZoom={4}/></Canvas>:<p>{failed?'The model could not load. Use the routing photographs.':'Loading the assembly…'}</p>}
 </div>
}

import {useEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useFrame} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import {loadBundle,type Bundle} from './cadAssets'
import {motorCheckScene} from './motorCheckScene'
import {motorId} from './driveMap'
import type {Build} from './buildContent'

function Movement({bundle,build,finger,movement,playing,replay,isolated}:{bundle:Bundle;build:Build;finger:string;movement:number;playing:boolean;replay:number;isolated:boolean}){
 const elapsed=useRef(0)
 const scene=useMemo(()=>{
  const name=finger[0].toUpperCase()+finger.slice(1),code=finger==='pinky'?'P':name[0],segment=movement<2?'DP':movement<4?'PP':'AP'
  return motorCheckScene(bundle,build,motorId(`${code}-${segment}`,build),'hand',undefined,{owners:isolated?[`${name} DP`,`${name} PP`]:[`${name} DP`,`${name} PP`,`${name} AP`],bare:isolated})
 },[bundle,build,finger,movement,isolated])
 useEffect(()=>{elapsed.current=0},[scene,replay])
 useEffect(()=>()=>scene.dispose(),[scene])
 useFrame((_,delta)=>{
  if(playing)elapsed.current+=delta
  const t=Math.min(elapsed.current/2.4,1),smooth=(1-Math.cos(t*Math.PI))/2
  scene.setAngle(movement>=4?scene.towardPinkySign*(movement===4?1:-1)*.25*smooth:scene.sign*.6*(movement%2===0?smooth:1-smooth))
 })
 return <primitive object={scene.view}/>
}

export function CadFingerMovement({build,...props}:{build:Build;finger:string;movement:number;playing:boolean;replay:number;isolated:boolean}){
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`,[loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState('')
 useEffect(()=>{let active=true;loadBundle(key).then(bundle=>{if(active)setLoaded({key,bundle})}).catch(()=>{if(active)setFailed(key)});return()=>{active=false}},[key])
 if(loaded?.key!==key)return <p>{failed===key?'The finger model could not load. Reopen this step to retry.':'Loading the selected finger…'}</p>
 return <Canvas orthographic camera={{position:[0,0,1000],near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.4}/><directionalLight position={[300,500,600]} intensity={2.5}/><directionalLight position={[-300,100,-400]} intensity={1.5}/><Movement bundle={loaded.bundle} build={build} {...props}/><OrbitControls enablePan={false} enableZoom={false}/></Canvas>
}

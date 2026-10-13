import {useEffect,useMemo,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {Html,Line,OrbitControls} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadKey,cadPieces,disposePieces} from './cadScene'
import {conduitData,vectors} from './conduitPaths'
import apAnchors from './fingerApAnchorRoutes.json'
import {MOVEMENTS} from './fingerMovements'
import type {Build} from './buildContent'

function Outlets({bundle,build,finger,movement}:{bundle:Bundle;build:Build;finger:string;movement:number}){
 const {camera,size,invalidate}=useThree()
 const model=useMemo(()=>{
  const name=(finger[0].toUpperCase()+finger.slice(1)) as 'Index'|'Middle'|'Ring'|'Pinky'
  const pieces=cadPieces(bundle,build),part=pieces.find(p=>p.part.label===`${name} AP`)!
  const data=conduitData(build).ap[name],anchors=apAnchors[cadKey(build)][name]
  const paths=(['DP-flex','DP-ext','PP-flex','PP-ext'] as const).map(k=>vectors(data[k]))
  const direction=paths.reduce((v,p)=>v.add(p.at(-1)!.clone().sub(p.at(-2)!).normalize()),new THREE.Vector3()).normalize()
  const points=[...paths.map(p=>p.at(-1)!),...(['AP-p','AP-t'] as const).map(k=>new THREE.Vector3().fromArray(anchors.mouths[k]))]
  return {pieces,part,points,direction,center:part.bounds.getCenter(new THREE.Vector3()),extent:part.bounds.getSize(new THREE.Vector3()).length()}
 },[bundle,build,finger])
 useEffect(()=>()=>disposePieces(model.pieces),[model])
 useEffect(()=>{
  camera.position.copy(model.center).addScaledVector(model.direction,100)
  camera.up.set(0,0,-1);camera.lookAt(model.center)
  if(camera instanceof THREE.OrthographicCamera){camera.zoom=Math.min(size.width,size.height)/(model.extent*1.05);camera.updateProjectionMatrix()}
  invalidate()
 },[camera,size,model,invalidate])
 return <><primitive object={model.part.object}/>{model.points.map((point,i)=>{
  const labelOffset=point.clone().sub(model.center).projectOnPlane(model.direction).normalize().multiplyScalar(8)
  return <group key={i} position={point}>
  <mesh renderOrder={3}><sphereGeometry args={[i===movement?.8:.3,20,12]}/><meshBasicMaterial color={i===movement?'#286747':'#d8e4dc'} depthTest={false}/></mesh>
  {i===movement&&<><Line points={[new THREE.Vector3(),labelOffset]} color="#286747" lineWidth={1.5} depthTest={false}/><Html center position={labelOffset}><span className="assembly-outlet-name">{MOVEMENTS[i][0]}</span></Html></>}
 </group>})}<OrbitControls target={model.center} enablePan={false} minZoom={3} maxZoom={30}/></>
}

export function FingerOutlets({build,finger,movement}:{build:Build;finger:string;movement:number}){
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel`
 const [loaded,setLoaded]=useState<{key:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState('')
 useEffect(()=>{let active=true;loadBundle(key).then(bundle=>{if(active)setLoaded({key,bundle})}).catch(()=>{if(active)setFailed(key)});return()=>{active=false}},[key])
 return <figure className="assembly-finger-outlets"><figcaption>{finger[0].toUpperCase()+finger.slice(1)} AP · underside</figcaption><div className="assembly-finger-outlet-canvas" aria-label={`${finger} AP outlet for ${MOVEMENTS[movement][0]}`}>
  {loaded?.key===key?<Canvas key={`${key}-${finger}`} orthographic frameloop="demand" camera={{near:.1,far:1000}} dpr={[1,2]}><ambientLight intensity={1.4}/><directionalLight position={[100,300,200]} intensity={2.5}/><directionalLight position={[-100,-200,-200]} intensity={2}/><Outlets bundle={loaded.bundle} build={build} finger={finger} movement={movement}/></Canvas>:<p>{failed===key?'Unable to load the AP view. Reopen this step to retry.':'Loading AP outlets…'}</p>}
 </div><p>Pull <strong>{MOVEMENTS[movement][0]}</strong> from the marked {movement<4?'channel':'side anchor'}. Leave the other five ends slack.</p></figure>
}

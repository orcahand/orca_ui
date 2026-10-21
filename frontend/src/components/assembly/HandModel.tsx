import { useEffect, useMemo, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { finishMaterial, loadBundle, type Bundle } from './cadAssets'
import type { Part } from './assemblyParts'
import type { Build } from './buildContent'

function matchesPart(part:Part,selected:string,instanceNode:string) {
  if(['DP','PP','AP','TP'].includes(selected))return new RegExp(`\\b${selected}\\b`).test(part.label)
  if(selected==='Carpals')return part.category==='Carpals'||part.label==='Palm skin'
  if(selected==='Wrist')return part.areas.Wrist?.includes(instanceNode)??false
  if(selected==='Tower')return part.areas.Tower?.includes(instanceNode)??false
  return part.label===selected
}
function Render({bundle,build,selected,face}:{bundle:Bundle;build:Build;selected:string;face:string}) {
  const group=useMemo(()=>{
    const clone=bundle.scene.clone(true)
    const map=new Map<string,Part>();bundle.inventory.parts.forEach(p=>p.nodes.forEach(n=>map.set(n,p)))
    clone.traverse(node=>{
      if(!(node instanceof THREE.Mesh))return
      let current:THREE.Object3D|null=node,part:Part|undefined,instanceNode=''
      while(current&&!part){part=map.get(current.name);if(part)instanceNode=current.name;current=current.parent}
      if(!part)return
      const mat=finishMaterial(part,build,node.geometry),match=matchesPart(part,selected,instanceNode)
      mat.transparent=!match;mat.opacity=match?1:.10;mat.depthWrite=match
      node.material=mat;node.renderOrder=match?2:0
    })
    const box=new THREE.Box3().setFromObject(clone),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3())
    clone.position.sub(center)
    const upright=new THREE.Group();upright.add(clone)
    if(size.x>size.y&&size.x>size.z)upright.rotation.z=Math.PI/2
    else if(size.z>size.y)upright.rotation.x=-Math.PI/2
    const view=new THREE.Group();view.add(upright);view.rotation.y=face==='palmar'?Math.PI:0
    view.scale.setScalar(480/Math.max(size.x,size.y,size.z))
    return view
  },[bundle,build,selected,face])
  useEffect(()=>()=>group.traverse(n=>{if(n instanceof THREE.Mesh)(n.material as THREE.Material).dispose()}),[group])
  return <primitive object={group}/>
}
export function HandModel({build,selected,face}:{build:Build;selected:string;face:'palmar'|'dorsal'}) {
  const side=build.side,version=build.version==='touch'?'touch':'base',key=`${version}-${side}-dynamixel`
  const [loaded,setLoaded]=useState<{side:string;bundle:Bundle}|null>(null),[failed,setFailed]=useState(false)
  useEffect(()=>{let live=true;setFailed(false);loadBundle(key).then(bundle=>{if(live)setLoaded({side:key,bundle})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[key])
  return <div className="assembly-hand-label-render" aria-label={`${version} ${side} hand, ${face} view; ${selected} highlighted`}>
    {loaded?.side===key?<Canvas key={`${key}-${face}`} orthographic frameloop="demand" dpr={[1,2]} camera={{position:[0,0,1000],zoom:1,near:.1,far:4000}}><ambientLight intensity={1.5}/><hemisphereLight intensity={1.8}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-600]} intensity={2}/><Render bundle={loaded.bundle} build={build} selected={selected} face={face}/><OrbitControls enablePan={false} minZoom={.7} maxZoom={2}/></Canvas>:<p>{failed?'The hand render could not load. Reopen this step to retry.':'Loading the hand…'}</p>}
    <span className="assembly-render-direction">Distal · toward fingertips ↑</span>
  </div>
}

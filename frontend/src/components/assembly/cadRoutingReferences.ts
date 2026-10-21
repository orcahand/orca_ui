import * as THREE from 'three'
import {cadPieces,disposePieces,TENDON_COLORS} from './cadScene'
import {conduitData,connectorData,vectors} from './conduitPaths'
import {ChannelCurve} from './channelStrands'
import channels from './channelRoutes.json'
import {cadKey} from './cadScene'
import {TENDONS} from './guide'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadRoutingReference(bundle:Bundle,build:Build,kind:'wrist-groups'|'carpal-rows'|'pp-pair'){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
 const labels:{text:string;point:THREE.Vector3}[]=[]
 let routePoints:THREE.Vector3[],names:string[],direction:THREE.Vector3,up:THREE.Vector3|undefined
 if(kind==='wrist-groups'||kind==='carpal-rows'){
  for(const p of pieces.filter(p=>['Carpals','Touch carpals','Carpal core'].includes(p.part.label)))group.add(p.object)
  const data=conduitData(build)
  const starts=data.carpals.map(p=>new THREE.Vector3().fromArray(p.at(-1)!))
  // Direction arrows describe which wrist side receives each row, not the free-span shape.
  const ends=starts.map((p,i)=>new THREE.Vector3(p.x,p.y,Math.sign(data.wrist[i][0][2])*13))
  routePoints=[...starts,...ends];names=[...TENDONS,...TENDONS]
  direction=new THREE.Vector3(0,-1,0);up=new THREE.Vector3(0,0,-1)
  if(kind==='carpal-rows'){
   for(const [i,point] of starts.entries()){
    const mesh=new THREE.Mesh(new THREE.SphereGeometry(.5,16,12),new THREE.MeshBasicMaterial({color:i<16?'#c05d43':'#188b9a',depthTest:false}))
    mesh.position.copy(point);mesh.renderOrder=5
    group.add(mesh);extra.push(mesh)
   }
   for(const [start,text] of [[0,'Dorsal row · 16 tendons'],[16,'Palmar row · 16 tendons']] as const){
    const point=starts[start+8].clone()
    labels.push({text,point})
   }
  }
 }else{
  const pp=pieces.find(p=>p.part.label==='Index PP')!
  group.add(pp.object)
  const exits=connectorData(build).ppExits.Index
  const paths=channels[cadKey(build)].p33.map((p,i)=>{
   const points=vectors(p.fixed),exit=new THREE.Vector3().fromArray(exits[i===0?'DP-flex':'DP-ext'])
   let nearest=0
   points.forEach((point,j)=>{if(point.distanceToSquared(exit)<points[nearest].distanceToSquared(exit))nearest=j})
   return [exit,...points.slice(nearest+1)]
  })
  routePoints=[];names=['DP flex','DP ext']
  const tangent=new THREE.Vector3()
  paths.forEach((points,i)=>{
   const end=points.at(-1)!,out=end.clone().sub(points.at(-2)!).normalize()
   tangent.add(out)
   points.push(end.clone().addScaledVector(out,10))
   const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),600,.19,12,false),new THREE.MeshStandardMaterial({color:TENDON_COLORS[i+2],roughness:.7}))
   group.add(mesh);extra.push(mesh)
   routePoints.push(new THREE.Vector3().fromArray(exits[i===0?'DP-flex':'DP-ext']))
  })
  routePoints.push(...paths.map(p=>p.at(-1)!.clone()))
  direction=tangent.normalize().add(new THREE.Vector3(build.side==='right'?-.7:.7,0,-.45)).normalize()
 }
 return {group,routePoints,names,direction,up,labels,dispose:()=>{disposePieces(pieces);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

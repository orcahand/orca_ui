import * as THREE from 'three'
import {cadPieces,cadKey,disposePieces,fade} from './cadScene'
import {channelStrands} from './channelStrands'
import frames from './jointFrames.json'
import routes from './channelRoutes.json'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export type JointPreparation='upper-pin'|'pin-clearance'|'pp-underside'|'pp-finish'

export function cadJointPreparation(bundle:Bundle,build:Build,kind:JointPreparation){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
 const pp=pieces.find(p=>p.part.label==='Index PP')!,dp=pieces.find(p=>p.part.label==='Index DP')!
 const frame=frames[cadKey(build)].Index,x=new THREE.Vector3().fromArray(frame.x),y=new THREE.Vector3().fromArray(frame.y),z=new THREE.Vector3().fromArray(frame.z)
 const origin=new THREE.Vector3().fromArray(frame.origin),labels:{text:string;point:THREE.Vector3}[]=[]
 const prep=kind.startsWith('pp-')
 let strands:ReturnType<typeof channelStrands>|undefined
 let focus:THREE.Box3|undefined
 group.add(pp.object)
 const direction=y.clone().addScaledVector(x,.35).addScaledVector(z,-.35).normalize(),up=z.clone()
 if(prep){
  // Project the inspection cue onto this export's curved underside, without adding print defects.
  const surface:THREE.Vector3[]=[];pp.object.updateMatrixWorld(true)
  pp.object.traverse(n=>{if(n instanceof THREE.Mesh){const positions=n.geometry.attributes.position;for(let i=0;i<positions.count;i++)surface.push(new THREE.Vector3().fromBufferAttribute(positions,i).applyMatrix4(n.matrixWorld))}})
  const side=surface.reduce((value,p)=>Math.max(value,p.clone().sub(origin).dot(y)),-Infinity)
  const points=Array.from({length:49},(_,i)=>{
   const target=origin.clone().addScaledVector(x,Math.cos(Math.PI+i*Math.PI/48)*9.7).addScaledVector(z,Math.sin(Math.PI+i*Math.PI/48)*9.7).addScaledVector(y,side)
   return surface.reduce((a,b)=>a.distanceToSquared(target)<b.distanceToSquared(target)?a:b).clone()
  })
  const line=new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),96,.25,8,false),new THREE.MeshBasicMaterial({color:kind==='pp-underside'?'#c48237':'#287d72',depthTest:false}))
  line.renderOrder=5;group.add(line);extra.push(line)
  labels.push({text:'PP underside',point:points[24]})
  focus=pp.bounds.clone()
 }else{
  group.add(dp.object)
  const pins=pieces.filter(p=>p.part.label.startsWith('Pin')&&pp.bounds.clone().expandByScalar(1).containsPoint(p.center))
  const short=pins.filter(p=>p.part.label==='Pin · 2 × 6').sort((a,b)=>a.center.distanceToSquared(dp.center)-b.center.distanceToSquared(dp.center))
  if(short.length!==2)throw new Error(`Expected two PP 2 × 6 pins, found ${short.length}`)
  const upper=short[0],lower=short[1]
  if(kind==='pin-clearance')focus=new THREE.Box3().setFromPoints([upper.center,lower.center]).expandByScalar(8)
  for(const p of pins){group.add(p.object);if(kind==='upper-pin'&&p===upper){const axis=p.axis.clone();if(axis.dot(direction)<0)axis.negate();p.object.position.copy(axis).multiplyScalar(13)}}
  for(const p of pieces.filter(p=>p.part.label.startsWith('Bearing')&&p.owner==='Index DP'))group.add(p.object)
  fade(pp,kind==='pin-clearance'?.32:.65);fade(dp,.5)
  strands=channelStrands(build,pieces);strands.update();group.add(strands.group)
  if(focus)focus.union(pp.bounds).union(dp.bounds).union(new THREE.Box3().setFromObject(strands.group))
  labels.push({text:'Upper 2 × 6 pin',point:upper.center.clone().add(upper.object.position)})
  labels.push({text:'Lower 2 × 6 pin',point:lower.center.clone()})
  if(kind==='pin-clearance'){
   const target=upper.center.clone().lerp(lower.center,.5).addScaledVector(z,-4)
   const path=routes[cadKey(build)].p33[0].fixed.map(p=>new THREE.Vector3().fromArray(p))
   labels.push({text:'DP tendons',point:path.reduce((a,b)=>a.distanceToSquared(target)<b.distanceToSquared(target)?a:b)})
  }
 }
 return {group,labels,direction,up,focus,parts:pieces.filter(p=>p.object.parent===group).map(p=>p.part.label),dispose:()=>{disposePieces(pieces);strands?.dispose();extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

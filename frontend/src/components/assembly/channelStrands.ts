import * as THREE from 'three'
import routes from './channelRoutes.json'
import thumbRoutes from './thumbChannelRoutes.json'
import ppAnchors from './ppAnchorRoutes.json'
import frames from './jointFrames.json'
import {cadKey,TENDON_COLORS,type CadPiece} from './cadScene'
import type {Build} from './buildContent'

// Preserve CAD-checked polylines; a spline can cut through a channel wall.
export class ChannelCurve extends THREE.Curve<THREE.Vector3> {
 private lengths:number[]=[0]
 private points:THREE.Vector3[]
 constructor(points:THREE.Vector3[]){super();this.points=points;for(let i=1;i<points.length;i++)this.lengths.push(this.lengths[i-1]+points[i].distanceTo(points[i-1]))}
 getPoint(t:number,target=new THREE.Vector3()){
  const distance=THREE.MathUtils.clamp(t,0,1)*this.lengths.at(-1)!
  let lo=1,hi=this.lengths.length-1
  while(lo<hi){const mid=(lo+hi)>>1;if(this.lengths[mid]<distance)lo=mid+1;else hi=mid}
  const a=this.lengths[lo-1],b=this.lengths[lo]
  return target.copy(this.points[lo-1]).lerp(this.points[lo],b===a?0:(distance-a)/(b-a))
 }
}
export function channelStrands(build:Build,pieces:CadPiece[],finger:'Index'|'Thumb'='Index'){
 const dp=pieces.find(p=>p.part.label===`${finger} DP`)!,pp=pieces.find(p=>p.part.label===`${finger} PP`)!,group=new THREE.Group()
 const down=new THREE.Vector3().fromArray(frames[cadKey(build)][finger].z).negate()
 const source=finger==='Thumb'?thumbRoutes[cadKey(build)]:routes[cadKey(build)].p33
 const paths=source.map((path,i)=>{
  const material=new THREE.MeshBasicMaterial({color:TENDON_COLORS[[2,3,0,1][i]]}),mesh=new THREE.Mesh(new THREE.BufferGeometry(),material)
  const fixed=path.fixed.map(p=>new THREE.Vector3().fromArray(p));fixed.push(fixed.at(-1)!.clone().addScaledVector(down,14))
  group.add(mesh)
  return {moving:path.moving.map(p=>new THREE.Vector3().fromArray(p)),fixed,mesh,material}
 })
 const anchors=(finger==='Thumb'?[]:ppAnchors[cadKey(build)].paths).map((path,i)=>{
  const material=new THREE.MeshBasicMaterial({color:i===0?'#55c4cf':'#f29b58'}),mesh=new THREE.Mesh(new THREE.BufferGeometry(),material)
  const fixed=path.map(p=>new THREE.Vector3().fromArray(p));fixed.push(fixed.at(-1)!.clone().addScaledVector(down,14))
  group.add(mesh)
  return {moving:[] as THREE.Vector3[],fixed,mesh,material}
 })
 paths.push(...anchors)
 function update(){
  for(const path of paths){
   const moving=path.moving.map(p=>p.clone().applyQuaternion(dp.object.quaternion).add(dp.object.position)),fixed=path.fixed.map(p=>p.clone().applyQuaternion(pp.object.quaternion).add(pp.object.position))
   path.mesh.geometry.dispose();path.mesh.geometry=new THREE.TubeGeometry(new ChannelCurve([...moving,...fixed]),700,.14,8,false)
  }
 }
 return {group,count:paths.length,update,dispose:()=>paths.forEach(p=>{p.mesh.geometry.dispose();p.material.dispose()})}
}

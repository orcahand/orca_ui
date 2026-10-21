import * as THREE from 'three'
import routes from './thumbTpChannelRoutes.json'
import {ChannelCurve} from './channelStrands'
import {cadKey,type CadPiece} from './cadScene'
import type {Build} from './buildContent'

export function thumbTpStrands(build:Build,pieces:CadPiece[]){
 const ap=pieces.find(p=>p.part.label==='Thumb AP')!,tp=pieces.find(p=>p.part.label==='Thumb TP')!,group=new THREE.Group()
 const colors=['#d99d54','#81bb50','#d3bd50','#ae86eb','#f26962','#29bfcb']
 const strands=routes[cadKey(build)].map((path,i)=>{
  const material=new THREE.MeshBasicMaterial({color:colors[i]??'#f7faf4',transparent:true}),mesh=new THREE.Mesh(new THREE.BufferGeometry(),material)
  group.add(mesh)
  return {moving:path.moving.map(p=>new THREE.Vector3().fromArray(p)),fixed:path.fixed.map(p=>new THREE.Vector3().fromArray(p)),mesh,material,selection:i<6?i:-1}
 })
 function update(_displacement:THREE.Vector3,_slack:number,selected:number){
  const transform=(points:THREE.Vector3[],piece:CadPiece)=>points.map(p=>p.clone().applyQuaternion(piece.object.quaternion).add(piece.object.position))
  for(const path of strands){
   const points=[...transform(path.moving,ap),...transform(path.fixed,tp)]
   path.mesh.geometry.dispose();path.mesh.geometry=new THREE.TubeGeometry(new ChannelCurve(points),1000,.14,10,false)
   path.material.opacity=path.selection<0?.45:path.selection===selected?1:.2
  }
 }
 return {group,count:strands.length,update,dispose:()=>strands.forEach(p=>{p.mesh.geometry.dispose();p.material.dispose()})}
}

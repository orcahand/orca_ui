import * as THREE from 'three'
import thumbRoutes from './thumbApChannelRoutes.json'
import fingerRoutes from './fingerApChannelRoutes.json'
import thumbAnchors from './thumbApAnchorRoutes.json'
import fingerAnchors from './apAnchorRoutes.json'
import {ChannelCurve} from './channelStrands'
import {cadKey,TENDON_COLORS,type CadPiece} from './cadScene'
import type {Build} from './buildContent'

export function apStrands(build:Build,pieces:CadPiece[],finger:'Index'|'Thumb'){
 const key=cadKey(build),pp=pieces.find(p=>p.part.label===`${finger} PP`)!,ap=pieces.find(p=>p.part.label===`${finger} AP`)!,group=new THREE.Group()
 const routes=finger==='Thumb'?thumbRoutes:fingerRoutes,anchors=finger==='Thumb'?thumbAnchors:fingerAnchors
 const paths=routes[key].map((path,i)=>({moving:path.moving.map(p=>new THREE.Vector3().fromArray(p)),fixed:path.fixed.map(p=>new THREE.Vector3().fromArray(p)),selection:[2,3,0,1][i]}))
 for(const path of anchors[key].paths){
  const fixed=path.map(p=>new THREE.Vector3().fromArray(p)).reverse(),end=fixed.at(-1)!,direction=end.clone().sub(fixed.at(-2)!).normalize()
  fixed.push(end.clone().addScaledVector(direction,12))
  paths.push({moving:[],fixed,selection:-1})
 }
 const strands=paths.map(path=>{
  const material=new THREE.MeshBasicMaterial({color:path.selection<0?'#f7faf4':TENDON_COLORS[path.selection],transparent:true}),mesh=new THREE.Mesh(new THREE.BufferGeometry(),material)
  group.add(mesh);return {...path,mesh,material}
 })
 function update(_displacement:THREE.Vector3,_slack:number,selected:number){
  for(const path of strands){
   const transform=(points:THREE.Vector3[],piece:CadPiece)=>points.map(p=>p.clone().applyQuaternion(piece.object.quaternion).add(piece.object.position))
   const points=[...transform(path.moving,pp),...transform(path.fixed,ap)]
   path.mesh.geometry.dispose();path.mesh.geometry=new THREE.TubeGeometry(new ChannelCurve(points),900,.14,10,false)
   path.material.opacity=path.selection<0||path.selection===selected?1:.8
  }
 }
 return {group,count:strands.length,update,dispose:()=>strands.forEach(p=>{p.mesh.geometry.dispose();p.material.dispose()})}
}

import * as THREE from 'three'
import {ChannelCurve,channelStrands} from './channelStrands'
import {apStrands} from './apStrands'
import {thumbTpStrands} from './thumbTpStrands'
import {carpalStrands} from './carpalStrands'
import {bridge,conduitData,vectors} from './conduitPaths'
import type {Build} from './buildContent'
import {TENDON_COLORS,type CadPiece} from './cadScene'
export function assemblyStrands(build:Build,step:string,pieces:CadPiece[]){
 if(step==='p33')return channelStrands(build,pieces)
 if(step==='p46')return channelStrands(build,pieces,'Thumb')
 if(step==='p42'||step==='p54')return apStrands(build,pieces,step==='p54'?'Thumb':'Index')
 if(step==='p62')return thumbTpStrands(build,pieces)
 if(step==='p64'||step==='p68')return carpalStrands(build,pieces,step==='p68')
 if(step==='p89')return wristStrands(build,pieces)
 return null
}

function wristStrands(build:Build,pieces:CadPiece[]){
 const data=conduitData(build),group=new THREE.Group()
 type Connection={moving:CadPiece;fixed:CadPiece;a:THREE.Vector3[];b:THREE.Vector3[];selection:number;color:string}
 const connections:Connection[]=[],piece=(label:string)=>pieces.find(p=>p.part.label===label)!
 const carpals=piece(build.version==='touch'?'Touch carpals':'Carpals')
 const add=(moving:CadPiece,fixed:CadPiece,a:THREE.Vector3[],b:THREE.Vector3[],selection:number,color=TENDON_COLORS[selection%8])=>connections.push({moving,fixed,a,b,selection,color})
 for(let index=0;index<32;index++){
  const wrist=vectors(data.wrist[index]),end=wrist.at(-1)!,out=end.clone().sub(wrist.at(-2)!).normalize()
  wrist.push(end.clone().addScaledVector(out,12))
  add(carpals,piece('Wrist frame'),vectors(data.carpals[index]),wrist,index)
 }
 const paths=connections.map(c=>{
  const material=new THREE.MeshBasicMaterial({color:c.color,transparent:true}),mesh=new THREE.Mesh(new THREE.BufferGeometry(),material);group.add(mesh);return {...c,mesh,material}
 })
 function update(_displacement:THREE.Vector3,_slack:number,selected:number){
  for(const p of paths){
   const transform=(points:THREE.Vector3[],part:CadPiece)=>points.map(v=>v.clone().applyQuaternion(part.object.quaternion).add(part.object.position))
   const a=transform(p.a,p.moving),b=transform(p.b,p.fixed),points=[...a,...bridge(a,b).slice(1),...b.slice(1)]
   p.mesh.geometry.dispose();p.mesh.geometry=new THREE.TubeGeometry(new ChannelCurve(points),600,.18,8,false);p.material.opacity=p.selection===selected?1:.8
  }
 }
 return {group,update,count:paths.length,dispose:()=>paths.forEach(p=>{p.mesh.geometry.dispose();p.material.dispose()})}
}

import * as THREE from 'three'
import paths from './spoolPaths.json'
import {ChannelCurve} from './channelStrands'
import {ease,type CadPiece} from './cadScene'
import {stopperGeometry} from './stopperGeometry'

export function spoolWinding(spool:CadPiece,kind:'bottom'|'top'){
 const data=paths[kind],group=new THREE.Group(),origin=new THREE.Vector3().fromArray(data.origin)
 const lead=data.lead.map(p=>new THREE.Vector3().fromArray(p))
 const channel=data.channel.map(p=>new THREE.Vector3().fromArray(p)),seatedTail=data.tail.map(p=>new THREE.Vector3().fromArray(p)),end=channel.at(-1)!
 const axis=end.clone().sub(channel.at(-8)!).normalize(),stopper=stopperGeometry(.6)
 const knotCenter=end.clone().addScaledVector(axis,kind==='bottom'?1.2:.6)
 const anchoredChannel=channel.map(p=>p.clone())
 while(anchoredChannel.length>1&&anchoredChannel.at(-1)!.distanceTo(end)<.3)anchoredChannel.pop()
 anchoredChannel.push(knotCenter.clone().addScaledVector(axis,-.9))
 const across=new THREE.Vector3(0,0,1).cross(axis).normalize(),up=axis.clone().cross(across).normalize()
 if(kind==='bottom'){across.negate();up.negate()}
 stopper.group.position.copy(knotCenter);stopper.group.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(across,up,axis))
 if(kind==='bottom')stopper.group.rotateZ(170*Math.PI/180)
 if(kind==='top')stopper.group.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),axis)
 const material=new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.72}),strand=new THREE.Mesh(new THREE.BufferGeometry(),material),tail=new THREE.Mesh(new THREE.BufferGeometry(),material)
 strand.name='Spool tendon';tail.name='Knot tail';stopper.group.name='Ashley stopper';group.position.copy(spool.center);group.add(strand,stopper.group,tail)
 function update(position:number){
  const wound=ease((position-.12)/.52),turns=Math.max(.025,wound*3),count=Math.ceil(turns*160),coil:THREE.Vector3[]=[]
  for(let i=0;i<=count;i++){
   const t=1-turns/3+(turns/3)*i/count,angle=data.theta+data.direction*(t-1)*Math.PI*6
   let axial=kind==='bottom'?t-.5:.5-t
   if(kind==='bottom'){
    // Leave room for the stopper and returning tail at the anchor mouth.
    const opening=Math.atan2(end.y-origin.y,end.x-origin.x),distance=Math.abs(Math.atan2(Math.sin(angle-opening),Math.cos(angle-opening)))
    if(distance<.65)axial+=(t<.3?-.27:t<.6?-.29:.44)*(1+Math.cos(distance/.65*Math.PI))/2
   }
   coil.push(origin.clone().add(new THREE.Vector3(data.radius*Math.cos(angle),data.radius*Math.sin(angle),axial)))
  }
  const tangent=coil[1].clone().sub(coil[0]).normalize(),incoming=coil[0].clone().addScaledVector(tangent,-22)
  strand.geometry.dispose();strand.geometry=new THREE.TubeGeometry(new ChannelCurve([incoming,...coil,...lead.slice(1),...(position>.64?anchoredChannel:channel).slice(1)]),Math.max(800,coil.length+channel.length),.14,12,false)
  const tuck=ease((position-.73)/.27),height=kind==='bottom'?.6:-.8,radius=Math.abs(height)/2,normal=new THREE.Vector3(0,0,Math.sign(height)),start=knotCenter.clone().addScaledVector(axis,.9)
  const fold=[start,...Array.from({length:41},(_,i)=>{
   const angle=i/40*Math.PI
   return knotCenter.clone().addScaledVector(axis,1.1+radius*Math.sin(angle)).addScaledVector(normal,radius*(1-Math.cos(angle)))
  }),knotCenter.clone().addScaledVector(normal,Math.abs(height)),...seatedTail.map(p=>p.clone().add(new THREE.Vector3(0,0,kind==='top'?-.66:0)))]
  let length=0
  for(let i=1;i<fold.length;i++){
   const span=fold[i-1].distanceTo(fold[i])
   if(length+span>=5){const endpoint=fold[i].clone();fold[i].copy(fold[i-1]).lerp(endpoint,(5-length)/span);fold.length=i+1;break}
   length+=span
  }
  tail.geometry.dispose();tail.geometry=new THREE.TubeGeometry(new ChannelCurve(fold),240,.14,12,false)
  tail.geometry.setDrawRange(0,Math.floor(tuck*tail.geometry.index!.count/6)*6)
  stopper.group.visible=position>.64;tail.visible=position>.73
  group.position.copy(spool.center).add(spool.object.position)
 }
 update(0)
 return {group,update,dispose:()=>{strand.geometry.dispose();tail.geometry.dispose();material.dispose();stopper.dispose()}}
}

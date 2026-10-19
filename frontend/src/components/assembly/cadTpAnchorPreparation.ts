import * as THREE from 'three'
import {cadPieces,cadKey,disposePieces} from './cadScene'
import {ChannelCurve} from './channelStrands'
import {anchorStopper} from './anchorStopper'
import routes from './thumbTpChannelRoutes.json'
import frames from './thumbTpFrames.json'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadTpAnchorPreparation(bundle:Bundle,build:Build,phase:'thread'|'reinforce'){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),part=pieces.find(p=>p.part.label==='Thumb TP')!
 const key=cadKey(build),up=new THREE.Vector3().fromArray(frames[key].basis[2]),across=new THREE.Vector3().fromArray(frames[key].basis[0])
 const extra:THREE.Mesh[]=[],stoppers:ReturnType<typeof anchorStopper>[]=[],labels:{text:string;point:THREE.Vector3}[]=[]
 group.add(part.object)
 function cord(points:THREE.Vector3[]){
  const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),Math.max(160,points.length*2),.14,16,false),new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.75}))
  group.add(mesh);extra.push(mesh)
 }
 for(const [i,route] of routes[key].slice(6).entries()){
  const points=route.fixed.map(p=>new THREE.Vector3().fromArray(p)).reverse(),seat=points.at(-1)!
  cord(points)
  if(phase==='thread'){
   cord([seat,seat.clone().addScaledVector(up,20)])
   if(i===0)labels.push({text:'Working end (20 cm)',point:seat.clone().addScaledVector(up,17)})
  }else{
   const stopper=anchorStopper(.7,3),position=seat.clone().addScaledVector(up,10),rotation=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1),up)
   stopper.group.position.copy(position);stopper.group.quaternion.copy(rotation);group.add(stopper.group);stoppers.push(stopper)
   const entry=stopper.entry.clone().applyQuaternion(rotation).add(position),exit=stopper.exit.clone().applyQuaternion(rotation).add(position)
   cord([seat,entry]);cord([exit,exit.clone().addScaledVector(up,7)])
   if(i===0)labels.push({text:'Ashley stopper + 3 single knots',point:position})
  }
  if(i===1)labels.push({text:'TP anchor housing',point:seat})
 }
 return {group,labels,direction:up.clone().addScaledVector(across,.7).normalize(),up:across,dispose:()=>{disposePieces(pieces);stoppers.forEach(s=>s.dispose());extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

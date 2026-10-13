import * as THREE from 'three'
import {cadPieces,cadKey,disposePieces,fade} from './cadScene'
import {ChannelCurve} from './channelStrands'
import {anchorStopper} from './anchorStopper'
import anchors from './apAnchorRoutes.json'
import thumbAnchors from './thumbApAnchorRoutes.json'
import seatedKnots from './seatedApKnots.json'
import {conduitData,vectors} from './conduitPaths'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export type ApAnchorPreparation='thread'|'reinforce'|'settle'|'trim'|'tuck'

export function cadApAnchorPreparation(bundle:Bundle,build:Build,phase:ApAnchorPreparation,thumb=false){
 const pieces=cadPieces(bundle,build),part=pieces.find(p=>p.part.label===(thumb?'Thumb AP':'Index AP'))!,group=new THREE.Group(),extra:THREE.Mesh[]=[]
 group.add(part.object)
 const data=(thumb?thumbAnchors:anchors)[cadKey(build)],up=new THREE.Vector3().fromArray(data.up),across=new THREE.Vector3().fromArray(data.across),front=new THREE.Vector3().fromArray(data.front)
 const points=data.paths[0].map(p=>new THREE.Vector3().fromArray(p)),entrance=points[0],seat=points.at(-1)!
 const outside=entrance.clone().addScaledVector(entrance.clone().sub(points[1]).normalize(),12)
 const labels:{text:string;point:THREE.Vector3}[]=[],seatedStoppers:ReturnType<typeof anchorStopper>[]=[]
 const seated=phase==='settle'||phase==='tuck'
 const cordOutlines:THREE.Vector3[][]=[]
 function line(points:THREE.Vector3[],radius=.14,color='#f7f8f4'){
  const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),Math.max(80,points.length*2),radius,12,false),new THREE.MeshStandardMaterial({color,roughness:.75}))
  group.add(mesh);extra.push(mesh)
  if(seated&&radius===.14)cordOutlines.push(points)
 }
 for(const kind of ['PP-ext','PP-flex'] as const){
  const points=vectors(conduitData(build).ap[thumb?'Thumb':'Index'][kind])
  points[0].add(points[0].clone().sub(points[1]).normalize());points.at(-1)!.add(points.at(-1)!.clone().sub(points.at(-2)!).normalize())
  for(const [radius,side] of [[.75,THREE.FrontSide],[.45,THREE.BackSide]] as const){
   const tube=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),100,radius,20,false),new THREE.MeshStandardMaterial({color:'#f7faf4',roughness:.8,side}))
   group.add(tube);extra.push(tube)
  }
 }
 if(!seated)line([outside,...points])
 const knot=seat.clone().addScaledVector(up,10),stopper=anchorStopper(thumb?.7:.65,thumb?3:1)
 const rotation=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1),up)
 stopper.group.position.copy(knot);stopper.group.quaternion.copy(rotation)
 const knotEntry=stopper.entry.clone().applyQuaternion(rotation).add(knot),knotExit=stopper.exit.clone().applyQuaternion(rotation).add(knot)
 if(phase==='thread'||phase==='reinforce'){
  if(phase==='thread')line([seat,seat.clone().addScaledVector(up,20)])
  else{line([seat,knotEntry]);line([knotExit,knotExit.clone().addScaledVector(up,8)]);group.add(stopper.group)}
  labels.push({text:phase==='thread'?'Tendon':thumb?'Ashley stopper + 3 single knots':'Ashley stopper + single knot',point:phase==='thread'?entrance:knot})
  labels.push({text:phase==='thread'?'Working end · 20 cm':'Knot housing',point:phase==='thread'?seat.clone().addScaledVector(up,18):seat})
 }else if(phase==='trim'){
  const from=knotExit,end=from.clone().addScaledVector(up,5)
  line([seat,knotEntry]);line([from,end]);group.add(stopper.group)
  const offset=front.clone().multiplyScalar(2)
  line([from.clone().add(offset),end.clone().add(offset)],.045,'#b16d23')
  for(const p of [from,end])line([p.clone().add(offset).addScaledVector(front,-.5),p.clone().add(offset).addScaledVector(front,.5)],.045,'#b16d23')
  labels.push({text:'Reinforced stopper',point:knot})
  labels.push({text:'Tail · 5 mm',point:from.clone().lerp(end,.5).add(offset)})
 }
 if(seated){
  fade(part,.22)
  const poses=seatedKnots[cadKey(build)][thumb?'Thumb':'Index']
  poses.slice(0,phase==='settle'?1:2).forEach((pose,i)=>{
   const path=data.paths[i].map(p=>new THREE.Vector3().fromArray(p))
   const free=path[0].clone().addScaledVector(path[0].clone().sub(path[1]).normalize(),12)
   const knot=anchorStopper(thumb?.7:.65,thumb?3:1);knot.group.position.fromArray(pose.position);knot.group.quaternion.fromArray(pose.quaternion);group.add(knot.group);seatedStoppers.push(knot)
   const entry=knot.entry.clone().applyQuaternion(knot.group.quaternion).add(knot.group.position),exit=knot.exit.clone().applyQuaternion(knot.group.quaternion).add(knot.group.position)
   line([free,...path,entry])
   if(phase==='settle')line([exit,exit.clone().addScaledVector(up,12)])
   else line(pose.tail.map(p=>new THREE.Vector3().fromArray(p)))
   if(i===0){
    labels.push({text:'Reinforced stopper',point:knot.group.position.clone()})
    labels.push({text:phase==='settle'?'Untrimmed working end':'Tucked tail',point:phase==='settle'?exit.clone().addScaledVector(up,10):new THREE.Vector3().fromArray(pose.tail[Math.floor(pose.tail.length/2)])})
   }else labels.push({text:'Second stopper',point:knot.group.position.clone()})
  })
 }
 return {group,labels,cordOutlines,direction:up.clone().addScaledVector(front,thumb?-.3:.65).addScaledVector(across,thumb?.65:.45).normalize(),up:across,frameObjects:seated?[phase==='tuck'?part.object:group]:undefined,dispose:()=>{disposePieces(pieces);stopper.dispose();seatedStoppers.forEach(k=>k.dispose());extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

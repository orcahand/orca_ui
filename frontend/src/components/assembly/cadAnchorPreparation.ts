import * as THREE from 'three'
import {cadPieces,cadKey,disposePieces} from './cadScene'
import {ChannelCurve} from './channelStrands'
import {anchorStopper} from './anchorStopper'
import routes from './channelRoutes.json'
import frames from './jointFrames.json'
import ppRoutes from './ppAnchorRoutes.json'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export type AnchorPreparation='dp-feed'|'dp-seat'|'dp-tuck'|'pp-feed'|'pp-tuck'

export function cadAnchorPreparation(bundle:Bundle,build:Build,kind:AnchorPreparation){
 const pp=kind.startsWith('pp'),phase=kind.split('-')[1]
 const pieces=cadPieces(bundle,build),part=pieces.find(p=>p.part.label===(pp?'Index PP':'Index DP'))!,group=new THREE.Group(),extra:THREE.Mesh[]=[]
 group.add(part.object)
 const key=cadKey(build),frame=frames[key].Index,x=new THREE.Vector3().fromArray(frame.x),y=new THREE.Vector3().fromArray(frame.y),z=new THREE.Vector3().fromArray(frame.z)
 const opening=pp?new THREE.Vector3().fromArray(ppRoutes[key].opening):y
 const paths=(pp?ppRoutes[key].paths:routes[key].p33.map(p=>p.moving)).map(path=>path.map(v=>new THREE.Vector3().fromArray(v)))
 const starts=paths.map(p=>p[0]),center=starts[0].clone().lerp(starts[1],.5)
 const labels:{text:string;point:THREE.Vector3}[]=[],stoppers:ReturnType<typeof anchorStopper>[]=[]
 function cord(points:THREE.Vector3[],radius=.14){
  const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),Math.max(120,points.length*2),radius,12,false),new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.75}))
  group.add(mesh);extra.push(mesh)
 }
 const freeEnds:THREE.Vector3[]=[]
 paths.forEach(points=>{
  const end=points.at(-1)!
  freeEnds.push(end.clone().addScaledVector(z,-14));cord([...points,freeEnds.at(-1)!])
 })
 if(phase!=='tuck'){
  const feed=phase==='feed',a=starts[0].clone().addScaledVector(opening,feed?8:2),b=starts[1].clone().addScaledVector(opening,feed?8:2)
  const loop=new THREE.CubicBezierCurve3(a,a.clone().addScaledVector(opening,feed?10:4).addScaledVector(z,feed?7:2),b.clone().addScaledVector(opening,feed?10:4).addScaledVector(z,feed?-7:-2),b).getPoints(100)
  if(feed){
   let previous=0,from=starts[0]
   for(const index of [33,66]){
    const stopper=anchorStopper(.65),tangent=loop[index+1].clone().sub(loop[index-1]).normalize()
    const rotation=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,0,1),tangent)
    stopper.group.position.copy(loop[index]);stopper.group.quaternion.copy(rotation);group.add(stopper.group);stoppers.push(stopper)
    const entry=stopper.entry.clone().applyQuaternion(rotation).add(loop[index]),exit=stopper.exit.clone().applyQuaternion(rotation).add(loop[index])
    let before=index,after=index
    while(before>previous&&loop[before].distanceTo(loop[index])<1.7)before--
    while(after<loop.length-1&&loop[after].distanceTo(loop[index])<2.5)after++
    cord([from,...loop.slice(previous,before+1),entry]);from=exit;previous=after
   }
   cord([from,...loop.slice(previous),starts[1]])
   labels.push({text:'Ashley stopper + single knot',point:loop[33]})
   labels.push({text:'Knot housing',point:center})
  }else{
   cord([starts[0],...loop,starts[1]])
   labels.push({text:'Reinforced stoppers',point:center})
   labels.push({text:'Connecting loop',point:loop[50]})
  }
 }else{
  labels.push({text:'Knot housing',point:center})
  
 }
 const direction=opening.clone().addScaledVector(x,.35).addScaledVector(z,-.1).normalize()
 const focus=part.bounds.clone().expandByScalar(3)
 for(const p of [...paths.flat(),...freeEnds])focus.expandByPoint(p)
 if(phase==='feed')focus.expandByPoint(center.clone().addScaledVector(opening,20))
 return {group,labels,direction,up:z,focus,dispose:()=>{disposePieces(pieces);stoppers.forEach(k=>k.dispose());extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

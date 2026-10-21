import * as THREE from 'three'
import {cadPieces,disposePieces,fade,nearest} from './cadScene'
import {conduitData,vectors} from './conduitPaths'
import {ChannelCurve} from './channelStrands'
import paths from './spoolPaths.json'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadSpoolPreparation(bundle:Bundle,build:Build,phase:'overview'|'thread'){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
 const labels:{text:string;point:THREE.Vector3}[]=[]
 const cordOutlines:THREE.Vector3[][]=[]
 const line=(points:THREE.Vector3[],radius=.14,color='#f7f8f4')=>{
  const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),Math.max(160,points.length*2),radius,16,false),new THREE.MeshStandardMaterial({color,roughness:.7}))
  group.add(mesh);extra.push(mesh)
 }
 let direction:THREE.Vector3
 if(phase==='overview'){
  const selected=pieces.filter(p=>['Motor tower','Wrist frame','Dynamixel XC330 motor','Bottom spool','Ratchet','M2 hex nut','M2 × 4 socket screw'].includes(p.part.label))
  selected.forEach(p=>group.add(p.object))
  const wrist=pieces.find(p=>p.part.label==='Wrist frame')!,spools=selected.filter(p=>p.part.label==='Bottom spool')
  const visible=spools.filter(p=>p.center.z<0).sort((a,b)=>b.center.y-a.center.y)
  const outlets=conduitData(build).wrist
  for(const [i,path] of outlets.entries()){
   const points=vectors(path),end=points.at(-1)!,out=end.clone().sub(points.at(-2)!).normalize()
   points.push(end.clone().addScaledVector(out,10));line(points,.18,i<16?'#c05d43':'#188b9a')
  }
  const tower=pieces.find(p=>p.part.label==='Motor tower')!
  const target=new THREE.Vector3(tower.bounds.min.x,tower.center.y,tower.bounds.min.z),surface=new THREE.Vector3();let distance=Infinity
  group.updateMatrixWorld(true)
  tower.object.traverse(n=>{if(n instanceof THREE.Mesh){const position=n.geometry.attributes.position,point=new THREE.Vector3();for(let i=0;i<position.count;i++){point.fromBufferAttribute(position,i).applyMatrix4(n.matrixWorld);const d=point.distanceToSquared(target);if(d<distance){distance=d;surface.copy(point)}}}})
  labels.push({text:'Wrist outlets',point:new THREE.Vector3().fromArray(outlets[8].at(-1)!)} ,{text:'Bottom spools',point:visible[0].center.clone()},{text:'Motor tower',point:surface})
  direction=new THREE.Vector3(.2,.08,-1)
  // The wrist frame remains assembled; the top spools and hull covers are fitted later.
  fade(wrist,.4)
 }else{
  const motor=pieces.find(p=>p.part.label==='Dynamixel XC330 motor'&&p.center.z<0)!
  const spool=nearest(pieces.filter(p=>p.part.label==='Bottom spool'),motor.center)
  group.add(spool.object);fade(spool,.36)
  const channel=vectors(paths.bottom.channel).map(p=>p.add(spool.center))
  const lead=vectors(paths.bottom.lead).map(p=>p.add(spool.center)),entry=lead[0],exit=channel.at(-1)!
  const incoming=entry.clone().addScaledVector(entry.clone().sub(lead[1]).normalize(),18)
  const axis=exit.clone().sub(channel.at(-8)!).normalize(),end=exit.clone().addScaledVector(axis,80)
  line([incoming,...lead,...channel.slice(1),end])
  cordOutlines.push([incoming,entry],[exit,end])
  const across=new THREE.Vector3(-axis.y,axis.x,0).normalize(),offset=across.clone().multiplyScalar(-5)
  line([exit.clone().add(offset),end.clone().add(offset)],.07,'#285b45')
  for(const point of[exit,end])line([point.clone().add(offset).addScaledVector(across,-1),point.clone().add(offset).addScaledVector(across,1)],.07,'#285b45')
  labels.push({text:'Anchor channel',point:channel[Math.floor(channel.length/2)].clone()},{text:'8 cm',point:exit.clone().lerp(end,.5).add(offset)},{text:'Working end',point:end.clone()})
  direction=new THREE.Vector3(0,0,1)
 }
 return {group,labels,direction,cordOutlines,dispose:()=>{disposePieces(pieces);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

import * as THREE from 'three'
import {cadPieces,disposePieces,fade} from './cadScene'
import {wristTendonPath,conduitData} from './conduitPaths'
import {ChannelCurve} from './channelStrands'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

/** Side view of the measured channels and their seated carpal-to-wrist spans. */
export function cadWristCrossing(bundle:Bundle,build:Build){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
 const selected=pieces.filter(p=>['Carpals','Touch carpals','Carpal core','Wrist frame'].includes(p.part.label))
 for(const piece of selected){group.add(piece.object);fade(piece,piece.part.label==='Carpal core'?.12:.22)}
 const data=conduitData(build),focus=new THREE.Box3()
 selected.forEach(p=>focus.union(p.bounds))
 const labels:{text:string;point:THREE.Vector3}[]=[]
 for(const [start,color,from,to] of [[0,'#c05d43','Dorsal row','Palmar wrist'],[16,'#188b9a','Palmar row','Dorsal wrist']] as const){
  for(let i=start;i<start+16;i++){
   const points=wristTendonPath(build,i)
   const end=points.at(-1)!,out=end.clone().sub(points.at(-2)!).normalize()
   points.push(end.clone().addScaledVector(out,8))
   const strand=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),1000,.18,12,false),new THREE.MeshStandardMaterial({color,roughness:.65}))
   strand.name=`Tendon ${i+1}`;group.add(strand);extra.push(strand)
   points.forEach(p=>focus.expandByPoint(p))
  }
  const carpal=data.carpals[start+8],wrist=data.wrist[start+8]
  labels.push({text:from,point:new THREE.Vector3().fromArray(carpal.at(-1)!)},{text:to,point:new THREE.Vector3().fromArray(wrist.at(-1)!)})
 }
 return {group,labels,focus,direction:new THREE.Vector3(build.side==='right'?1:-1,.06,.12),dispose:()=>{disposePieces(pieces);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

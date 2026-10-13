import * as THREE from 'three'
import frames from './thumbTpFrames.json'
import {cadKey,cadPieces,disposePieces} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadThumbTpFace(bundle:Bundle,build:Build,face:'entry'|'exit'){
 const all=cadPieces(bundle,build),group=new THREE.Group(),frame=frames[cadKey(build)],tp=all.find(p=>p.part.label==='Thumb TP')!
 const axes=frame.basis.map(a=>new THREE.Vector3().fromArray(a)),origin=new THREE.Vector3().fromArray(frame.origin)
 const point=(x:number,z:number)=>origin.clone().addScaledVector(axes[0],x).addScaledVector(axes[2],z)
 group.add(tp.object)
 for(const pin of all.filter(p=>p.part.label==='Pin · 2 × 30'&&tp.bounds.clone().expandByScalar(1).containsPoint(p.center)))group.add(pin.object)
 const colors=['#d99d54','#81bb50','#d3bd50','#ae86eb','#f26962','#29bfcb'],extra:THREE.Mesh[]=[]
 const routePoints=frame.lanes.map((x,i)=>{
  const start=point(x,1.5),end=point(x,-15),mesh=new THREE.Mesh(new THREE.TubeGeometry(new THREE.LineCurve3(start,end),1,.14,12,false),new THREE.MeshBasicMaterial({color:colors[i]}))
  group.add(mesh);extra.push(mesh);return face==='entry'?start:end
 })
 const direction=axes[2].clone().multiplyScalar(face==='entry'?1:-1).addScaledVector(axes[1],.15).normalize()
 return {group,labels:[] as {text:string;point:THREE.Vector3}[],direction,up:axes[1],routePoints,names:['AP toward thumb','PP ext','DP ext','DP flex','PP flex','AP toward pinky'],dispose:()=>{disposePieces(all);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

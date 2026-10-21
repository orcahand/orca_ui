import * as THREE from 'three'
import {cadPieces,disposePieces,fade} from './cadScene'
import {conduitData,fingerRoute,vectors} from './conduitPaths'
import {TENDONS} from './guide'
import {ChannelCurve} from './channelStrands'
import {cadThumbTpFace} from './cadThumbTpFace'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadRouteFace(bundle:Bundle,build:Build,step:string,face:'entry'|'exit'){
 if(step==='p59'||step==='p62')return cadThumbTpFace(bundle,build,face)
 const all=cadPieces(bundle,build),group=new THREE.Group(),data=conduitData(build)
 const extra:THREE.Mesh[]=[]
 const finger=step==='p54'?'Thumb':'Index',kinds=['PP-ext','PP-flex','DP-flex','DP-ext'] as const
 const carpal=step==='p64'&&face==='entry'
 const label=carpal?(build.version==='touch'?'Touch carpals':'Carpals'):`${finger} AP`
 const piece=all.find(p=>p.part.label===label)!
 group.add(piece.object)
 if(step==='p15')fade(piece,1)
 const paths=step==='p64'?['AP-p','PP-ext','DP-ext','DP-flex','PP-flex','AP-t'].map(kind=>{
  const index=TENDONS.indexOf(`I-${kind}`)
  return carpal?vectors(data.carpals[index]):fingerRoute(build,index)
 }):kinds.map(kind=>vectors(data.ap[finger][kind]))
 if(step==='p15')for(const kind of ['PP-ext','PP-flex'] as const){
  const points=vectors(data.ap.Index[kind]);points[0].add(points[0].clone().sub(points[1]).normalize());points[points.length-1].add(points.at(-1)!.clone().sub(points.at(-2)!).normalize())
  for(const [radius,side] of [[.75,THREE.FrontSide],[.45,THREE.BackSide]] as const){const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),100,radius,20,false),new THREE.MeshStandardMaterial({color:'#f7faf4',roughness:.8,side}));group.add(mesh);extra.push(mesh)}
 }
 const routePoints=paths.map(p=>(face==='entry'?p[0]:p.at(-1)!).clone())
 const direction=paths.reduce((v,p)=>p.length>1?v.add(face==='entry'?p[0].clone().sub(p[1]).normalize():p.at(-1)!.clone().sub(p.at(-2)!).normalize()):v,new THREE.Vector3()).normalize()
 // A slight oblique view keeps the channel opening and the surrounding seat visible.
 direction.addScaledVector(new THREE.Vector3(0,0,1),.12).normalize()
 const focus=carpal?new THREE.Box3().setFromPoints(routePoints).expandByScalar(9):undefined
 const names=step==='p64'?['AP toward pinky','PP ext','DP ext','DP flex','PP flex','AP toward thumb']:kinds.map(k=>k.replace('-',' '))
 return {group,labels:step==='p15'?[{text:'PTFE · Ø1.5 / Ø0.9 mm',point:routePoints[0]},{text:'Liner end · 1 mm',point:routePoints[1]}]:[] as {text:string;point:THREE.Vector3}[],direction,focus,routePoints,names,dispose:()=>{disposePieces(all);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

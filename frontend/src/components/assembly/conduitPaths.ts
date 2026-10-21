import * as THREE from 'three'
import routes from './conduitRoutes.json'
import ports from './connectorPorts.json'
import anchors from './fingerApAnchorRoutes.json'
import fingerCarpals from './fingerCarpalRoutes.json'
import thumbCarpals from './thumbCarpalRoutes.json'
import {cadKey} from './cadScene'
import {TENDONS} from './guide'
import type {Build} from './buildContent'
export const vectors=(points:number[][])=>points.map(p=>new THREE.Vector3().fromArray(p))
export function conduitData(build:Build){return routes[cadKey(build)]}
export function connectorData(build:Build){return ports[cadKey(build)]}
// A free span leaves each opening along the channel tangent.
export function bridge(a:THREE.Vector3[],b:THREE.Vector3[]){
 const start=a.at(-1)!,end=b[0],length=start.distanceTo(end)*.32
 const outgoing=a.length>1?start.clone().sub(a.at(-2)!).normalize():end.clone().sub(start).normalize()
 const incoming=b.length>1?b[1].clone().sub(end).normalize():end.clone().sub(start).normalize()
 return new THREE.CubicBezierCurve3(start,start.clone().addScaledVector(outgoing,length),end.clone().addScaledVector(incoming,-length),end).getPoints(32)
}
export function wristTendonPath(build:Build,index:number){
 const data=conduitData(build),carpal=vectors(data.carpals[index]),wrist=vectors(data.wrist[index])
 // The x-ray follows the continuous, numbered carpal and wrist channels.
 return [...carpal,...bridge(carpal,wrist).slice(1),...wrist.slice(1)]
}
export function fingerRoute(build:Build,index:number){
 const data=conduitData(build),p=connectorData(build),[code,segment,kind]=TENDONS[index].split('-')
 const finger=({I:'Index',M:'Middle',R:'Ring',P:'Pinky'} as const)[code as 'I'|'M'|'R'|'P']
 if(!finger)return [new THREE.Vector3().fromArray(p.tpExits[String(index) as keyof typeof p.tpExits])]
 if(segment==='AP')return [new THREE.Vector3().fromArray(anchors[cadKey(build)][finger].mouths[`AP-${kind}` as 'AP-t'|'AP-p'])]
 return vectors(data.ap[finger][`${segment}-${kind}` as 'DP-flex'|'DP-ext'|'PP-flex'|'PP-ext'])
}
export function handTendonPath(build:Build,index:number){
 const downstream=wristTendonPath(build,index),route=(index>=8&&index<16?thumbCarpals:fingerCarpals)[cadKey(build)].find(p=>p.index===index)!
 const carpalStart=vectors(conduitData(build).carpals[index])[0]
 const end=route.fixed.findIndex(p=>new THREE.Vector3().fromArray(p).distanceToSquared(carpalStart)<1e-7)
 return [...vectors(route.moving),...vectors(route.fixed.slice(0,end)),...downstream]
}

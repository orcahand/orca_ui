import * as THREE from 'three'
import {cadPieces,disposePieces,fade} from './cadScene'
import {conduitData,vectors} from './conduitPaths'
import {ChannelCurve} from './channelStrands'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function tubePullScene(bundle:Bundle,build:Build,phase:0|1|2){
 const pieces=cadPieces(bundle,build),ap=pieces.find(p=>p.part.label==='Index AP')!,group=new THREE.Group(),extra:THREE.Mesh[]=[]
 if(phase>0){group.add(ap.object);fade(ap,.38)}
 const path=vectors(conduitData(build).ap.Index['PP-flex']),start=path[0],end=path.at(-1)!,axis=start.clone().sub(end).normalize()
 const tube=phase===2?[start.clone().addScaledVector(axis,1),...path,end.clone().addScaledVector(axis,-1)]:[start.clone().addScaledVector(axis,15),start.clone().addScaledVector(axis,6)]
 const tendon=phase===2?[tube[0].clone().addScaledVector(axis,2),...path,end.clone().addScaledVector(axis,-20)]:phase===0?[tube[0].clone().addScaledVector(axis,4),tube.at(-1)!.clone().addScaledVector(axis,-3)]:[tube[0].clone().addScaledVector(axis,2),...tube,...path,end.clone().addScaledVector(axis,-20)]
 function strand(points:THREE.Vector3[],radius:number,color:string,side:THREE.Side=THREE.FrontSide){const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),160,radius,20,false),new THREE.MeshStandardMaterial({color,roughness:.8,side}));group.add(mesh);extra.push(mesh)}
 strand(tube,.75,'#ddd8b9');strand(tube,.45,'#ddd8b9',THREE.BackSide);strand(tendon,.18,'#f7f8f4')
 const knot=tube[0].clone().addScaledVector(axis,.7),marker=new THREE.Mesh(new THREE.SphereGeometry(.7,20,12),new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.8}));marker.position.copy(knot);group.add(marker);extra.push(marker)
 const labels=[{text:'Stopper knot',point:knot},{text:'Free tendon end',point:tendon.at(-1)!},{text:'PTFE tube',point:tube[Math.floor(tube.length/2)]}]
 const direction=new THREE.Vector3(-.8,.25,-1).normalize()
 const exposed=[[tendon[0],tube[0]],[phase===0?tube.at(-1)!:end,tendon.at(-1)!]]
 return {group,labels,direction,cordOutlines:exposed,dispose:()=>{disposePieces(pieces);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

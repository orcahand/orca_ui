import * as THREE from 'three'
import shape from './spoolStopperShape.json'
import {ChannelCurve} from './channelStrands'

// A dressed noose grips the working end through its eye; the photo lesson shows how to tie it.
export function stopperGeometry(radius=.65){
 const group=new THREE.Group(),material=new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.78})
 const scale=radius/shape.radius,cord=shape.cord*scale
 const points=shape.points.map(p=>new THREE.Vector3().fromArray(p).multiplyScalar(scale))
 const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),points.length*2,cord,16,false),material);group.add(mesh)
 return {group,dispose:()=>{group.traverse(n=>{if(n instanceof THREE.Mesh)n.geometry.dispose()});material.dispose()}}
}

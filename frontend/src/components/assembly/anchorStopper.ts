import * as THREE from 'three'
import shapes from './anchorKnotShapes.json'
import {ChannelCurve} from './channelStrands'

// Dressed cord paths keep the reinforcing overhands around the Ashley stopper.
export function anchorStopper(radius=.65,reinforcements:1|3=1){
 const data=shapes[reinforcements],scale=radius/data.radius,points=data.points.map(p=>new THREE.Vector3().fromArray(p).multiplyScalar(scale))
 const group=new THREE.Group(),material=new THREE.MeshStandardMaterial({color:'#f7f8f4',roughness:.78})
 const geometry=new THREE.TubeGeometry(new ChannelCurve(points),points.length*2,data.cord*scale,16,false)
 group.add(new THREE.Mesh(geometry,material))
 return {group,entry:points[0].clone(),exit:points.at(-1)!.clone(),dispose:()=>{geometry.dispose();material.dispose()}}
}

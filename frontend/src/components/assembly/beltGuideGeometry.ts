import * as THREE from 'three'
import type {Inventory} from './assemblyParts'

// The flexible belt's imported waist passes outside a tensioning screw.
// Bend that waist through the clear gap between the two 4 mm PTFE sleeves.
export function fitBeltBetweenSleeves(scene:THREE.Group,inventory:Inventory){
 scene.updateMatrixWorld(true)
 const screws=inventory.parts.filter(p=>p.label==='M4 × 20 socket screw').flatMap(p=>p.nodes).map(name=>scene.getObjectByName(name)).filter((o):o is THREE.Object3D=>!!o)
 const belts=inventory.parts.filter(p=>p.label==='GT2 belt · 142 mm').flatMap(p=>p.nodes)
 if(screws.length!==2||!belts.length)return
 const centers=screws.map(o=>new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3()))
 const center=centers[0].clone().lerp(centers[1],.5),across=centers[1].clone().sub(centers[0]).normalize(),along=new THREE.Vector3(1,0,0).cross(across).normalize()
 const halfGap=centers[0].distanceTo(centers[1])/2-2-.3
 if(halfGap<=0)throw new Error('No clearance between wrist belt sleeves')
 for(const name of belts)scene.getObjectByName(name)?.traverse(node=>{
  if(!(node instanceof THREE.Mesh))return
  const original=node.geometry,geometry=original.clone(),positions=geometry.getAttribute('position'),inverse=node.matrixWorld.clone().invert(),point=new THREE.Vector3()
  for(let i=0;i<positions.count;i++){
   point.fromBufferAttribute(positions,i).applyMatrix4(node.matrixWorld)
   const relative=point.clone().sub(center),distance=Math.abs(relative.dot(along)),weight=1-THREE.MathUtils.smoothstep(distance,3.5,13)
   const lateral=relative.dot(across),inside=halfGap*Math.tanh(lateral/halfGap)
   point.addScaledVector(across,(inside-lateral)*weight).applyMatrix4(inverse);positions.setXYZ(i,point.x,point.y,point.z)
  }
  geometry.computeVertexNormals();geometry.computeBoundingBox();geometry.computeBoundingSphere();geometry.userData.beltBetweenSleeves=true;node.geometry=geometry
 })
}

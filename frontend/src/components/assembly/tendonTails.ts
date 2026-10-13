import * as THREE from 'three'
// Exposed free ends only. The routing diagrams show the channels inside each part.
export function tendonTails(ports:THREE.Vector3[],colors:string[]) {
 const group=new THREE.Group(),segments=24,geometry=new THREE.CylinderGeometry(.00032,.00032,1,8),cone=new THREE.ConeGeometry(.0013,.003,12)
 const tails=ports.map((port,i)=>{
  const material=new THREE.MeshBasicMaterial({color:colors[i],transparent:true}),mesh=new THREE.InstancedMesh(geometry,material,segments),arrow=new THREE.Mesh(cone,material)
  mesh.frustumCulled=false;arrow.rotation.x=Math.PI;group.add(mesh,arrow)
  return {port,mesh,arrow,material}
 })
 const dummy=new THREE.Object3D(),up=new THREE.Vector3(0,1,0)
 function update(active:number,pull:number){
  tails.forEach((tail,i)=>{
   const start=tail.port.clone(),end=start.clone().add(new THREE.Vector3((i-(tails.length-1)/2)*.008,0,-.025-(i===active?.020*pull:0)))
   const bend=start.clone().lerp(end,.5);if(i!==active)bend.x+=.008;else bend.x+=.004*(1-pull)
   const curve=new THREE.QuadraticBezierCurve3(start,bend,end),points=curve.getPoints(segments)
   for(let j=0;j<segments;j++){const delta=points[j+1].clone().sub(points[j]);dummy.position.copy(points[j]).add(points[j+1]).multiplyScalar(.5);dummy.quaternion.setFromUnitVectors(up,delta.clone().normalize());dummy.scale.set(1,delta.length(),1);dummy.updateMatrix();tail.mesh.setMatrixAt(j,dummy.matrix)}
   tail.mesh.instanceMatrix.needsUpdate=true;tail.material.opacity=i===active?1:.32;tail.arrow.visible=i===active;tail.arrow.position.copy(end);tail.arrow.quaternion.setFromUnitVectors(up,end.clone().sub(bend).normalize())
  })
 }
 return {group,update,dispose:()=>{geometry.dispose();cone.dispose();tails.forEach(t=>t.material.dispose())}}
}

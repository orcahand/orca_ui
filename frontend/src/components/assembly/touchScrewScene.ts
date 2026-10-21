import * as THREE from 'three'
import {cadPieces,disposePieces,nearest,fade} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'
import locations from './touchScrewLocations.json'

export const TOUCH_FINGERS=['Index','Middle','Ring','Pinky','Thumb'] as const
export type TouchFinger=typeof TOUCH_FINGERS[number]
export const SCREW_COLORS:Record<number,string>={3:'#73aa45',4:'#388bea',6:'#e4a149'}
export function touchScrewScene(bundle:Bundle,build:Build,finger:TouchFinger){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),view=new THREE.Group()
 const dp=pieces.find(p=>p.part.label===`${finger} DP`)!
 const sensor=nearest(pieces.filter(p=>p.part.label.includes('touch module')),dp.center)
 group.add(dp.object,sensor.object)
 const rows=locations[build.side][finger]
 const positions=rows.map(row=>new THREE.Vector3().fromArray(row.position))
 const average=(values:THREE.Vector3[])=>values.reduce((a,b)=>a.add(b),new THREE.Vector3()).multiplyScalar(1/values.length)
 const up=average(positions.filter((_,i)=>rows[i].location==='tip')).sub(average(positions.filter((_,i)=>rows[i].location==='lower'))).normalize()
 const outward=average(rows.map(row=>new THREE.Vector3().fromArray(row.outward))).normalize()
 const x=up.clone().cross(outward).normalize(),y=outward.clone().cross(x).normalize()
 const orientation=new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,outward)).invert()
 const geometries:THREE.BufferGeometry[]=[],materials:THREE.Material[]=[]
 const mesh=(geometry:THREE.BufferGeometry,material:THREE.Material,parent:THREE.Object3D)=>{geometries.push(geometry);materials.push(material);const m=new THREE.Mesh(geometry,material);parent.add(m);return m}
 const screws=rows.map((row,i)=>{
  const screw=new THREE.Group(),axis=new THREE.Vector3().fromArray(row.outward),seat=positions[i]
  screw.name=`${finger} ${row.location} screw ${i+1}`;screw.userData.screwLength=row.length
  screw.position.copy(seat);screw.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),axis);group.add(screw)
  // Dimensioned teaching fasteners; the CAD export lacks most installed M1.4s.
  const steel=new THREE.MeshStandardMaterial({color:'#bfc9ce',metalness:.65,roughness:.32})
  const shaft=mesh(new THREE.CylinderGeometry(.7,.7,row.length,24),steel,screw);shaft.rotation.x=Math.PI/2;shaft.position.z=-row.length/2
  const head=mesh(new THREE.CylinderGeometry(1.2,1.2,.7,32),steel,screw);head.rotation.x=Math.PI/2;head.position.z=.35
  for(const rotation of [0,Math.PI/2]){const slot=mesh(new THREE.BoxGeometry(1.55,.22,.025),new THREE.MeshBasicMaterial({color:'#34454c'}),screw);slot.position.z=.71;slot.rotation.z=rotation}
  const ring=mesh(new THREE.TorusGeometry(1.7,.13,8,48),new THREE.MeshBasicMaterial({color:SCREW_COLORS[row.length]}),screw);ring.position.z=row.recessDepth+.25
  const lineGeometry=new THREE.BufferGeometry().setFromPoints([seat,seat.clone().addScaledVector(axis,8)])
  geometries.push(lineGeometry);const lineMaterial=new THREE.LineDashedMaterial({color:SCREW_COLORS[row.length],dashSize:.8,gapSize:.5});materials.push(lineMaterial)
  const guide=new THREE.Line(lineGeometry,lineMaterial);guide.computeLineDistances();group.add(guide)
  return {screw,ring,guide,seat,axis,length:row.length,location:row.location}
 })
 // Fit once to the fully exploded model, keeping the camera stable as screws move.
 screws.forEach(s=>s.screw.position.copy(s.seat).addScaledVector(s.axis,8))
 const center=new THREE.Box3().setFromObject(group).getCenter(new THREE.Vector3());group.position.copy(center).negate();view.add(group);view.quaternion.copy(orientation).premultiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(-.1,.35,0)))
 const size=new THREE.Box3().setFromObject(view).getSize(new THREE.Vector3())
 const update=(length:number,exploded:number,seeThrough:boolean)=>{
  fade(dp,seeThrough?.22:1);fade(sensor,seeThrough?.22:1)
  screws.forEach(s=>{
   s.screw.position.copy(s.seat).addScaledVector(s.axis,exploded*8)
   s.screw.traverse(node=>{if(node instanceof THREE.Mesh){const m=node.material as THREE.Material;m.transparent=!!length&&length!==s.length;m.opacity=m.transparent?.2:1;m.depthWrite=!m.transparent}})
   s.guide.visible=exploded>0&&(!length||length===s.length)
   s.guide.geometry.setFromPoints([s.seat,s.seat.clone().addScaledVector(s.axis,exploded*8)]);s.guide.computeLineDistances()
  })
 }
 update(0,0,false)
 return {view,size,screws,update,dispose:()=>{disposePieces(pieces);geometries.forEach(g=>g.dispose());new Set(materials).forEach(m=>m.dispose())}}
}

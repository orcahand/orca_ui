import * as THREE from 'three'
import {cadPieces,disposePieces,ease} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

// The supplied STL uses X across the palm, Y through its depth, Z along the hand.
// Registration against the matching carpal body gives this assembly transform.
// Bore centers and head seats were measured from each cover STL (radius 0.7 mm).
export const COVER_HOLES={
 right:[[-12.782964,-14,-20.598411],[-11.174516,-15.5,17.231173],[21.573010,-13,-20.598411],[30.662086,-14,10.357779]],
 left:[[22.782964,-14,-20.598411],[21.174516,-15.5,17.231173],[-11.573010,-13,-20.598411],[-20.662086,-14,10.357779]],
}
export const coverTransform=(side:Build['side'])=>new THREE.Matrix4().makeRotationX(-Math.PI/2).setPosition(side==='right'?-14.75:-12.9,141.8,1.8770780631086)
export function carpalCoverScene(bundle:Bundle,build:Build,source:THREE.BufferGeometry,body:THREE.BufferGeometry){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),view=new THREE.Group()
 const fixed=pieces.filter(p=>['Carpal core','Touch connector board'].includes(p.part.label))
 fixed.forEach(p=>group.add(p.object))
 const geometries:THREE.BufferGeometry[]=[],materials:THREE.Material[]=[]
 const material=(color:string,metalness=0)=>{const m=new THREE.MeshStandardMaterial({color,metalness,roughness:metalness?.35:.65});materials.push(m);return m}
 const mesh=(geometry:THREE.BufferGeometry,m:THREE.Material,parent:THREE.Object3D=group)=>{geometries.push(geometry);const o=new THREE.Mesh(geometry,m);parent.add(o);return o}
 const transform=coverTransform(build.side),cover=mesh(source.clone().applyMatrix4(transform),material('#398ca4'));cover.name='Carpal cover'
 mesh(body.clone().applyMatrix4(transform),material('#29333b')).name='Touch carpals (separate printable body)'
 const board=fixed.find(p=>p.part.label==='Touch connector board')!
 const cableStart=new THREE.Vector3(board.center.x-.304,board.center.y-10.688,13.3)
 const curve=new THREE.CatmullRomCurve3([cableStart,cableStart.clone().add(new THREE.Vector3(0,-6,0)),cableStart.clone().add(new THREE.Vector3(0,-14,2)),cableStart.clone().add(new THREE.Vector3(build.side==='right'?-9:9,-25,7))])
 mesh(new THREE.TubeGeometry(curve,60,1.4,14,false),material('#444e57')).name='Connected board cable'
 const steel=material('#c3cbd0',.65),slotMaterial=material('#394049')
 const guideMaterial=new THREE.LineDashedMaterial({color:'#c38527',dashSize:1,gapSize:.8});materials.push(guideMaterial)
 const screws=COVER_HOLES[build.side].map((point,i)=>{
  const seat=new THREE.Vector3().fromArray(point).applyMatrix4(transform),object=new THREE.Group();object.name=`Carpal cover screw ${i+1}`;group.add(object)
  // 6 mm under-head length, 1.4 mm thread diameter. Head/drive are schematic.
  const shaft=mesh(new THREE.CylinderGeometry(.5,.5,5.4,20),steel,object);shaft.rotation.x=Math.PI/2;shaft.position.z=-2.7
  const tip=mesh(new THREE.ConeGeometry(.5,.6,20),steel,object);tip.rotation.x=-Math.PI/2;tip.position.z=-5.7
  const head=mesh(new THREE.CylinderGeometry(1.25,1.25,.75,28),steel,object);head.rotation.x=Math.PI/2;head.position.z=.375
  const thread=new THREE.CatmullRomCurve3(Array.from({length:241},(_,j)=>{const t=j/240,a=t*12*Math.PI*2;return new THREE.Vector3(.59*Math.cos(a),.59*Math.sin(a),-.18-t*5.1)}))
  mesh(new THREE.TubeGeometry(thread,360,.11,6,false),steel,object)
  for(const angle of [0,Math.PI/2]){const slot=mesh(new THREE.BoxGeometry(1.6,.22,.025),slotMaterial,object);slot.position.z=.76;slot.rotation.z=angle}
  const geometry=new THREE.BufferGeometry().setFromPoints([seat,seat.clone().add(new THREE.Vector3(0,0,38))]);geometries.push(geometry)
  const guide=new THREE.Line(geometry,guideMaterial);guide.computeLineDistances();group.add(guide)
  return {object,seat,guide}
 })
 const update=(progress:number)=>{
  const coverLift=24*(1-ease(progress/.6)),screwLift=14*(1-ease((progress-.6)/.4))
  cover.position.z=coverLift
  screws.forEach(({object,seat,guide})=>{
   object.position.copy(seat).add(new THREE.Vector3(0,0,coverLift+screwLift))
   object.rotation.z=ease((progress-.6)/.4)*Math.PI*6
   guide.visible=progress<.995
   guide.geometry.setFromPoints([seat,object.position]);guide.computeLineDistances()
  })
 }
 update(0)
 const center=new THREE.Box3().setFromObject(group).getCenter(new THREE.Vector3());group.position.copy(center).negate();view.add(group)
 view.rotation.set(-.18,build.side==='right'?-.48:.48,0)
 const size=new THREE.Box3().setFromObject(view).getSize(new THREE.Vector3())
 return {view,size,cover,screws,update,dispose:()=>{disposePieces(pieces);geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose())}}
}

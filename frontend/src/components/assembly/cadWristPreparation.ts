import * as THREE from 'three'
import {cadPieces,disposePieces,fade,nearest} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export type WristPreparation='tower-nuts'|'square-nuts'|'screw-sleeves'|'belt-position'|'fan-mounts'|'fans-fitted'

export function cadWristPreparation(bundle:Bundle,build:Build,kind:WristPreparation){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
 const labels:{text:string;point:THREE.Vector3}[]=[]
 const matching=(names:string[])=>pieces.filter(p=>names.includes(p.part.label))
 let direction=new THREE.Vector3(-1,.35,-.3),focus:THREE.Box3|undefined
 if(kind==='tower-nuts'){
  const tower=matching(['Motor tower'])[0],nuts=matching(['M4 hex nut'])
  if(nuts.length!==3)throw new Error('Expected three tower M4 nuts')
  group.add(tower.object);fade(tower,.18)
  focus=new THREE.Box3()
  for(const [i,nut] of nuts.entries()){
   const inward=nut.axis.clone()
   if(inward.dot(tower.center.clone().sub(nut.center))<0)inward.negate()
   nut.object.position.copy(inward).multiplyScalar(12);group.add(nut.object)
   const from=nut.center.clone().add(nut.object.position)
   group.add(new THREE.ArrowHelper(inward.clone().negate(),from.clone().addScaledVector(inward,-2),8,0x298a92,2,1))
   labels.push({text:`M4 nut ${i+1} (from inside)`,point:from})
   focus.union(nut.bounds)
  }
  focus.expandByScalar(15)
  direction.set(.35,1,-1)
 }else if(kind==='square-nuts'){
  const wrist=matching(['Wrist frame'])[0],nuts=matching(['M4 square nut'])
  if(nuts.length!==2)throw new Error('Expected two wrist square nuts')
  group.add(wrist.object)
  fade(wrist,.18)
  for(const [i,nut] of nuts.entries()){
   // Negative X is the wrist interior; the nuts enter the pockets from this side.
   nut.object.position.set(-12,0,0);group.add(nut.object)
   const from=nut.center.clone().add(nut.object.position)
   const arrow=new THREE.ArrowHelper(new THREE.Vector3(1,0,0),from.clone().add(new THREE.Vector3(2,0,0)),8,0x298a92,2,1)
   group.add(arrow)
   labels.push({text:`Square nut ${i+1} (insert from inside)`,point:from})
  }
  focus=wrist.bounds.clone()
  direction.set(-1,.6,-.7)
 }else if(kind==='fan-mounts'||kind==='fans-fitted'){
  const tower=matching(['Motor tower'])[0],fans=matching(['Cooling fan']),screws=matching(['M3 × 12 socket screw'])
  const nuts=matching(['M3 hex nut']).filter(p=>screws.some(s=>Math.abs(s.center.y-p.center.y)<.01&&Math.abs(s.center.z-p.center.z)<.01))
  if(fans.length!==2||screws.length!==2||nuts.length!==2)throw new Error('Expected two fan mounting sets')
  group.add(tower.object,...nuts.map(p=>p.object))
  direction=kind==='fan-mounts'?new THREE.Vector3(-1,0,0):new THREE.Vector3(-1,.12,.45)
  if(kind==='fans-fitted')group.add(...fans.concat(screws).map(p=>p.object))
  else for(const screw of screws){
   const ring=new THREE.Mesh(new THREE.TorusGeometry(4,.4,12,64),new THREE.MeshBasicMaterial({color:'#298a92',depthTest:false}))
   ring.rotation.y=Math.PI/2;ring.position.set(fans[0].bounds.max.x,screw.center.y,screw.center.z);ring.renderOrder=4;group.add(ring);extra.push(ring)
  }
  nuts.forEach((p,i)=>labels.push({text:kind==='fan-mounts'?`M3 nut pocket ${i+1}`:`Fan fixing ${i+1}`,point:p.center.clone().setX(fans[0].bounds.min.x)}))
 }else{
  const wrist=matching(['Wrist frame'])[0],screws=matching(['M4 × 20 socket screw']),nuts=matching(['M4 square nut'])
  if(screws.length!==2||nuts.length!==2)throw new Error('Expected two wrist tension screws')
  group.add(wrist.object,...matching(['M4 × 20 socket screw','M4 washer','M4 square nut']).map(p=>p.object))
  fade(wrist,.07)
  for(const screw of screws){
   const nut=nearest(nuts,screw.center),start=screw.bounds.min.x+.15,end=nut.bounds.min.x-.15
   // The guide specifies ID 2.7 / OD 4; trim each supplemental sleeve to the exposed shaft.
   const profile=new THREE.Shape();profile.absarc(0,0,2,0,Math.PI*2,false)
   const hole=new THREE.Path();hole.absarc(0,0,1.35,0,Math.PI*2,true);profile.holes.push(hole)
   const mesh=new THREE.Mesh(new THREE.ExtrudeGeometry(profile,{depth:end-start,steps:1,bevelEnabled:false,curveSegments:64}),new THREE.MeshStandardMaterial({color:'#e2dcc3',roughness:.58}))
   mesh.rotation.y=Math.PI/2;mesh.position.set(start,screw.center.y,screw.center.z);group.add(mesh);extra.push(mesh)
  }
  const center=screws[0].center.clone().lerp(screws[1].center,.5)
  if(kind==='belt-position'){
   group.add(...matching(['Carpal pulley','GT2 belt · 142 mm']).map(p=>p.object))
   const pulley=matching(['Carpal pulley'])[0],belt=matching(['GT2 belt · 142 mm'])[0]
   focus=belt.bounds.clone().union(pulley.bounds).union(screws[0].bounds).union(screws[1].bounds).expandByScalar(5)
   labels.push({text:'Wrist belt',point:center.clone().setX(belt.center.x)})
   labels.push({text:'Carpal pulley (hand side)',point:pulley.center.clone()})
   direction.set(-1,.15,-.28)
  }else{
   focus=screws[0].bounds.clone().union(screws[1].bounds).expandByScalar(7)
   labels.push({text:'PTFE (ID 2.7 / OD 4 mm)',point:screws[1].center.clone().setX((screws[1].bounds.min.x+nuts[1].bounds.min.x)/2)})
   labels.push({text:'PTFE sleeve',point:screws[0].center.clone().setX(screws[0].bounds.min.x+3)})
   direction.set(-.65,.6,-1)
  }
 }
 return {group,labels,direction,focus,parts:pieces.filter(p=>p.object.parent===group).map(p=>p.part.label),dispose:()=>{group.traverse(o=>{if(o instanceof THREE.ArrowHelper)o.dispose()});disposePieces(pieces);extra.forEach(m=>{m.geometry.dispose();(m.material as THREE.Material).dispose()})}}
}

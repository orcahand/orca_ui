import * as THREE from 'three'
import {cadKey,cadPieces,disposePieces,fade,framed,nearest} from './cadScene'
import frames from './livePoseFrames.json'
import {testJoint} from './jointTestControl'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

type JointFrame={restDegrees:number;pivot:number[];axis:number[];parent:string|null}

export function liveHandPoseScene(bundle:Bundle,build:Build,id:number){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),selected=testJoint(id,build)
 const data=frames[cadKey(build)] as Record<string,JointFrame>
 const joints=Object.entries(data).map(([name,f])=>({name,...f,pivot:new THREE.Vector3().fromArray(f.pivot),axis:new THREE.Vector3().fromArray(f.axis),matrix:new THREE.Matrix4()}))
 const byName=new Map(joints.map(j=>[j.name,j])),bodies=pieces.filter(p=>/^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label))
 const areas=(p:typeof pieces[number])=>Object.keys(p.part.areas).filter(a=>p.part.areas[a].includes(p.name))
 const ownerJoint=(owner:string)=>{
  const [finger,part]=owner.toLowerCase().split(' ')
  return `${finger}_${part==='tp'?'cmc':part==='ap'?'abd':part==='pp'?'mcp':finger==='thumb'?'dip':'pip'}`
 }
 const belongsToSelected=(name:string):boolean=>name===selected||(data[name]?.parent?belongsToSelected(data[name].parent!):false)
 const assigned=pieces.filter(p=>areas(p).some(a=>['Fingers','Thumb','Carpals'].includes(a))||p.part.label==='Wrist frame').map(p=>{
  const owner=p.owner??(bodies.includes(p)?p.part.label:nearest(bodies.filter(b=>areas(b).some(a=>areas(p).includes(a))),p.center)?.part.label)
  const name=p.part.label==='Wrist frame'?null:owner&&byName.has(ownerJoint(owner))?ownerJoint(owner):'wrist'
  group.add(p.object);p.object.matrixAutoUpdate=false
  fade(p,name&&belongsToSelected(name)?1:.38)
  return {piece:p,joint:name}
 })
 let previous:Record<string,number>={}
 function setPose(angles:Record<string,number>|null){
  const next=Object.fromEntries(joints.map(j=>[j.name,Number.isFinite(angles?.[j.name])?angles![j.name]:j.restDegrees]))
  if(joints.every(j=>Math.abs((previous[j.name]??Infinity)-next[j.name])<.025))return false
  for(const j of joints){
   const rotation=new THREE.Quaternion().setFromAxisAngle(j.axis,THREE.MathUtils.degToRad(next[j.name]-j.restDegrees))
   j.matrix.compose(j.pivot.clone().sub(j.pivot.clone().applyQuaternion(rotation)),rotation,new THREE.Vector3(1,1,1))
   if(j.parent)j.matrix.premultiply(byName.get(j.parent)!.matrix)
  }
  for(const {piece,joint} of assigned){piece.object.matrix.copy(joint?byName.get(joint)!.matrix:new THREE.Matrix4());piece.object.matrixWorldNeedsUpdate=true}
  previous=next;return true
 }
 setPose(Object.fromEntries(joints.map(j=>[j.name,0])))
 const view=framed(group,build,350,430)
 return {view,setPose,joints,assignments:assigned.map(({piece,joint})=>({name:piece.name,label:piece.part.label,joint})),dispose:()=>disposePieces(pieces)}
}

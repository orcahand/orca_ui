import * as THREE from 'three'
import {illustratedJointRange,rangeAngle} from './illustratedJointRange'
import {ASSEMBLY_MOTIONS} from './assemblyMotions'
import {assemblyStrands} from './assemblyStrands'
import {spoolWinding} from './spoolWinding'
import {cadPieces,disposePieces,ease,fade,framed,nearest,type CadPiece} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'
type Stage={piece:CadPiece;offset:THREE.Vector3;from:number;to:number;carry?:boolean}
export function assemblyScene(bundle:Bundle,build:Build,step:string){
 const all=cadPieces(bundle,build),group=new THREE.Group(),stages:Stage[]=[],included=new Set<CadPiece>(),spec=ASSEMBLY_MOTIONS[step]
 const pinOwners=new Map<CadPiece,string>()
 const add=(p:CadPiece)=>{if(!included.has(p)){included.add(p);group.add(p.object)}}
 const matching=(labels:string[])=>all.filter(p=>labels.includes(p.part.label))
 const stage=(p:CadPiece,offset:THREE.Vector3,from:number,to:number,carry=false)=>{add(p);stages.push({piece:p,offset,from,to,carry})}
 const special=['p99','p122','p126','p123'].includes(step)
 let focusBox:THREE.Box3|null=null,focusYaw=0
 let winding:ReturnType<typeof spoolWinding>|null=null
 let direction=new THREE.Vector3(0,1,0),gap=28
 if(step==='p99'||step==='p126'||step==='p123'){
  const motor=matching(['Dynamixel XC330 motor']).find(p=>p.center.z<0)!,motors=matching(['Dynamixel XC330 motor'])
  const owner=(p:CadPiece)=>nearest(motors,p.center)===motor&&p.center.distanceTo(motor.center)<36
  add(motor)
  const labels=step!=='p126'?['Bottom spool','Ratchet','M2 hex nut','M2 × 4 socket screw']:['Bottom spool','Ratchet','M2 hex nut','M2 × 4 socket screw','Top spool / tensioner','Spool cover','Spool ORCA insert','Bearing · 4 × 8 × 3','M2.5 × 8 socket screw']
  const picked=matching(labels).filter(owner),axis=new THREE.Vector3(0,0,Math.sign(motor.center.z)||1)
  picked.forEach(p=>{
   if(step==='p99'){
    const nut=p.part.label==='M2 hex nut',spool=p.part.label==='Bottom spool',screw=p.part.label.includes('screw')
    stage(p,axis.clone().multiplyScalar(nut?-18:spool?30:screw?48:58),nut?0:spool?.22:screw?.45:.73,nut?.22:spool?.45:screw?.73:1)
   } else if(step==='p126'&&['Top spool / tensioner','Spool cover','Spool ORCA insert','Bearing · 4 × 8 × 3','M2.5 × 8 socket screw'].includes(p.part.label)){
    const screw=p.part.label.includes('screw')
    stage(p,axis.clone().multiplyScalar(screw?55:28),screw?.9:.65,screw?1:.9)
   }else add(p)
  })
  if(step==='p123'||step==='p126'){
   const spool=picked.find(p=>p.part.label===(step==='p126'?'Spool cover':'Bottom spool'))!
   for(const p of included)fade(p,p===spool?1:.26)
   winding=spoolWinding(spool,step==='p126'?'top':'bottom');group.add(winding.group)
  }
 }else if(step==='p122'){
  matching(['Motor tower','Wrist frame','Wrist motor adapter','Wrist pulley','Dynamixel XC430 wrist motor','GT2 belt · 142 mm','Carpal pulley','M4 × 10 socket screw','M4 hex nut','M2 × 8 socket screw','Pin · 4 × 10']).forEach(add)
  const pulley=matching(['Wrist pulley'])[0],bearing=nearest(matching(['Bearing · 4 × 8 × 3']),pulley.center);add(bearing)
  const wrist=matching(['Wrist frame'])[0],motor=matching(['Dynamixel XC430 wrist motor'])[0]
  const axial=pulley.center.clone().sub(motor.center).normalize()
  focusBox=motor.bounds.clone().union(pulley.bounds).expandByScalar(24);focusYaw=Math.atan2(-axial.x,axial.z)
  for(const p of included){
   const label=p.part.label
   if(label==='Wrist motor adapter')stage(p,axial.clone().multiplyScalar(28),0,.16,true)
   else if(label==='M2 × 8 socket screw')stage(p,axial.clone().multiplyScalar(42),.16,.3,true)
   else if(label==='Wrist pulley'||label==='Pin · 4 × 10'||p===bearing)stage(p,axial.clone().multiplyScalar(p===bearing?55:42),.3,.5,true)
   else if(label==='M4 × 10 socket screw'||label==='M4 hex nut'){
    const axis=p.axis.clone();if(axis.dot(p.center.clone().sub(wrist.center))<0)axis.negate()
    stage(p,axis.multiplyScalar(label.includes('nut')?10:24),label.includes('nut')?.65:.82,label.includes('nut')?.8:1)
   }else if(label!=='Motor tower')stage(p,new THREE.Vector3(),0,1,true)
  }
 }else{
  let moving=matching(spec.moving),fixed=matching(spec.fixed)
  if(spec.single){const anchor=fixed[0];moving=spec.moving.flatMap(label=>{const p=nearest(matching([label]),anchor.center);return p?[p]:[]});fixed=spec.fixed.flatMap(label=>{const p=nearest(matching([label]),anchor.center);return p?[p]:[]})}
  moving.concat(fixed).forEach(add)
  if(step==='p33'||step==='p46'){
   const finger=step==='p46'?'Thumb':'Index'
   const pp=fixed.find(p=>p.part.label===`${finger} PP`)!,dp=moving.find(p=>p.part.label===`${finger} DP`)!
   const pins=all.filter(p=>p.part.label.startsWith('Pin ·')&&pp.bounds.clone().expandByScalar(1).containsPoint(p.center))
   if(step==='p46'){
    const upper=nearest(pins,dp.center)
    pins.filter(p=>p!==upper).forEach(add)
    const axis=upper.axis.clone();if(axis.dot(upper.center.clone().sub(pp.center))<0)axis.negate()
    stage(upper,axis.multiplyScalar(14),.8,1)
   }else{
    const lower=pins.filter(p=>p.part.label==='Pin · 2 × 6').sort((a,b)=>b.center.distanceToSquared(dp.center)-a.center.distanceToSquared(dp.center))[0]
    pins.filter(p=>p===lower||p.part.label==='Pin · 2 × 8').forEach(add)
   }
  }
  const movingBox=new THREE.Box3(),fixedBox=new THREE.Box3();moving.forEach(p=>movingBox.union(p.bounds));fixed.forEach(p=>fixedBox.union(p.bounds))
  direction=movingBox.getCenter(new THREE.Vector3()).sub(fixedBox.getCenter(new THREE.Vector3())).normalize()
  gap=Math.max(42,movingBox.getSize(new THREE.Vector3()).length()*.22)
  moving.forEach(p=>{
   // Opposite tower side plates approach independently along the lateral axis.
   const approach=step==='p135'?new THREE.Vector3(Math.sign(p.center.x-fixedBox.getCenter(new THREE.Vector3()).x),0,0):direction.clone()
   stage(p,approach.multiplyScalar(gap),.25,.78)
  })
  if(step==='p42'||step==='p54'){
   const finger=step==='p54'?'Thumb':'Index',pinLength=step==='p54'?10:8
   const pp=moving.find(p=>p.part.label===`${finger} PP`)!,ap=fixed.find(p=>p.part.label===`${finger} AP`)!
   for(const pin of all.filter(p=>p.part.label.startsWith('Pin ·'))){
    if(pp.bounds.clone().expandByScalar(1).containsPoint(pin.center)){stage(pin,direction.clone().multiplyScalar(gap),.25,.78);pinOwners.set(pin,`${finger} PP`)}
    else if(pin.part.label===`Pin · 2 × ${pinLength}`&&ap.bounds.clone().expandByScalar(1).containsPoint(pin.center)){
     const axis=pin.axis.clone();if(axis.dot(pin.center.clone().sub(ap.center))<0)axis.negate()
     stage(pin,axis.multiplyScalar(14),.78,.9)
    }
   }
  }
  if(step==='p62'){
   const pp=moving.find(p=>p.part.label==='Thumb PP')!,ap=moving.find(p=>p.part.label==='Thumb AP')!,tp=fixed.find(p=>p.part.label==='Thumb TP')!
   for(const pin of all.filter(p=>p.part.label.startsWith('Pin ·'))){
    const owner=[pp,ap,tp].find(p=>p.bounds.clone().expandByScalar(1).containsPoint(pin.center)&&(p===pp||pin.part.label===`Pin · 2 × ${p===ap?10:30}`))
    if(!owner)continue
    pinOwners.set(pin,owner.part.label)
    if(owner===tp)add(pin);else stage(pin,direction.clone().multiplyScalar(gap),.25,.78)
   }
  }
  if(step==='p64'||step==='p68'){
   for(const pin of all.filter(p=>p.part.label.startsWith('Pin ·'))){
    const owners=moving.filter(p=>p.bounds.clone().expandByScalar(1).containsPoint(pin.center)),owner=nearest(owners,pin.center)
    if(owner){pinOwners.set(pin,owner.part.label);stage(pin,direction.clone().multiplyScalar(gap),.25,.78)}
   }
  }
  if(step==='p89'){
   const wrist=fixed.find(p=>p.part.label==='Wrist frame')!
   // Touch finger skins and sensors are fitted after the tower chapter; the palm skin is already installed.
   for(const p of all){
    const skin=p.part.category==='Skins'&&(p.part.label==='Palm skin'||(build.version!=='touch'&&/ (DP|PP) skin$/.test(p.part.label)))
    const pin=p.part.label.startsWith('Pin ·')&&(spec.moving.includes(p.owner??'')||p.part.label==='Pin · 3 × 50')
    if(skin||pin)stage(p,direction.clone().multiplyScalar(gap),.25,.78)
   }
   matching(['M4 square nut']).forEach(add)
   matching(['M4 washer','M4 × 20 socket screw']).forEach(p=>{
    const axis=p.axis.clone();if(axis.dot(p.center.clone().sub(wrist.center))<0)axis.negate()
    stage(p,axis.multiplyScalar(p.part.label==='M4 washer'?16:28),p.part.label==='M4 washer'?.84:.9,p.part.label==='M4 washer'?.9:1)
   })
  }
  // Match a bearing to the closest segment in the complete assembly before selecting it.
  const bodies=all.filter(p=>/^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label)||['Carpals','Touch carpals','Wrist frame'].includes(p.part.label))
  if(['p33','p42','p46','p54','p62','p64','p68','p89'].includes(step)){
   for(const p of all.filter(p=>p.part.label.startsWith('Bearing'))){
    if(step!=='p89'&&!p.owner)continue
    const owner=p.owner?bodies.find(b=>b.part.label===p.owner):nearest(bodies,p.center);if(step==='p33'&&owner?.part.label==='Index PP')continue
    if(!owner||!included.has(owner)||p.center.distanceTo(owner.center)>43)continue
    const axis=p.axis.clone();if(axis.dot(p.center.clone().sub(owner.center))<0)axis.negate()
    if(fixed.includes(owner))stage(p,axis.multiplyScalar(14),['p42','p54'].includes(step)?.9:.72,step==='p89'?.84:1)
    else {add(p);stage(p,direction.clone().multiplyScalar(gap),.25,.78)}
   }
  }
 }
 const bearingJoints:Record<string,string[]>={p33:['Index DP'],p42:['Index PP'],p46:['Thumb DP'],p54:['Thumb PP'],p62:['Thumb AP'],p64:['Index AP','Middle AP','Ring AP','Pinky AP'],p68:['Thumb TP'],p89:['Wrist']}
 const inspections=(bearingJoints[step]??[]).map(name=>{
  const bearings=all.filter(p=>p.part.label.startsWith('Bearing')&&(name==='Wrist'?p.part.label==='Bearing · 8 × 13 × 4':p.owner===name))
  const pivot=bearings[0].center.clone().add(bearings[1].center).multiplyScalar(.5),axis=bearings[1].center.clone().sub(bearings[0].center).normalize()
  const [finger,segment]=name.split(' '),names=['DP','PP','AP','TP'].slice(0,['DP','PP','AP','TP'].indexOf(segment)+1).map(s=>`${finger} ${s}`)
  const moving=[...included].filter(p=>name==='Wrist'?(!spec.fixed.includes(p.part.label)&&!['M4 square nut','M4 washer','M4 × 20 socket screw'].includes(p.part.label)):names.includes(p.part.label)||names.includes(p.owner??pinOwners.get(p)??''))
  const joint=name==='Wrist'?'wrist':`${finger.toLowerCase()}_${segment==='TP'?'cmc':segment==='AP'?'abd':segment==='PP'?'mcp':finger==='Thumb'?'dip':'pip'}`
  return {pivot,axis,moving,range:illustratedJointRange(build,joint,axis)}
 })
 const selected=[...included],strands=special?null:assemblyStrands(build,step,selected)
 if(strands?.count)group.add(strands.group)
 if(step!=='p122')for(const s of stages)s.piece.object.position.copy(s.offset)
 const routing=['p42','p54','p64','p68','p89'].includes(step)
 const view=framed(group,build,step==='p122'?290:routing?370:310,['p99','p123','p126'].includes(step)?580:routing?450:400)
 if(step==='p123'||step==='p126'){
  const direction=new THREE.Vector3(-48,step==='p123'?-55:55,-24).normalize()
  view.quaternion.setFromRotationMatrix(new THREE.Matrix4().lookAt(direction,new THREE.Vector3(),new THREE.Vector3(0,1,0))).invert();view.scale.setScalar(1)
  const size=new THREE.Box3().setFromObject(view).getSize(new THREE.Vector3());view.scale.setScalar(Math.min(310/size.y,580/size.x))
 }
 if(step==='p68')view.rotation.y=build.side==='right'?3.65:-3.65
 const finalCenter=group.position.clone(),finalScale=view.scale.x,finalYaw=view.rotation.y
 function update(position:number,tendon:number,inspection?:'rotation'|'axial',channels=false){
  const checkPhase=position;if(inspection)position=1
  selected.forEach(p=>{p.object.quaternion.identity();p.object.position.set(0,0,0)})
  if(focusBox){
   const t=ease((position-.45)/.25),focusScale=280/Math.max(...focusBox.getSize(new THREE.Vector3()).toArray())
   group.position.copy(focusBox.getCenter(new THREE.Vector3()).negate()).add(new THREE.Vector3(0,-35,0)).lerp(finalCenter,t);view.scale.setScalar(THREE.MathUtils.lerp(focusScale,finalScale,t));view.rotation.y=THREE.MathUtils.lerp(focusYaw,finalYaw,t)
   for(const p of included)if(['Motor tower','Wrist frame'].includes(p.part.label)){fade(p,p.part.label==='Motor tower'?t:.12+.88*t);if(p.part.label==='Motor tower')p.object.visible=t>.01}
  }
  for(const s of stages){s.piece.object.position.copy(s.offset).multiplyScalar(1-ease((position-s.from)/(s.to-s.from)));if(s.carry)s.piece.object.position.y+=35*(1-ease((position-.5)/.3))}
  if(step==='p99')for(const s of stages)if(s.piece.part.label==='M2 hex nut')s.piece.object.position.z+=30*Math.sign(s.piece.center.z)*(1-ease((position-.22)/.23))
  winding?.update(step==='p126'?Math.max(0,Math.min(1,(position-.18)/.47)):position)
  if(step==='p126'){
   const top=selected.find(p=>p.part.label==='Spool cover')!,bearing=selected.find(p=>p.part.label==='Bearing · 4 × 8 × 3')!
   bearing.object.position.copy(top.object.position).addScaledVector(new THREE.Vector3(0,0,Math.sign(top.center.z)||1),14*(1-ease(position/.18)))
   // spoolWinding already follows the spool center plus its assembly offset.
   if(winding)winding.group.visible=position>=.18
  }
  if(winding)for(const p of included){
   const cover=p.part.label===(step==='p126'?'Spool cover':'Bottom spool')
   fade(p,step==='p126'&&p.part.label.startsWith('Bearing')?1:cover?(channels?(position<.18?.65:.35):1):.26)
  }
  if(inspection)for(const joint of inspections){
   const angle=inspection==='rotation'?rangeAngle(joint.range,(1-Math.cos(checkPhase*Math.PI*2))/2):0,shift=inspection==='axial'?Math.sin(checkPhase*Math.PI*2)*.65:0
   const rotation=new THREE.Quaternion().setFromAxisAngle(joint.axis,angle),offset=joint.pivot.clone().sub(joint.pivot.clone().applyQuaternion(rotation)).addScaledVector(joint.axis,shift)
   for(const piece of joint.moving){piece.object.quaternion.copy(rotation);piece.object.position.copy(offset)}
  }
  if(strands)strands.group.visible=!inspection
  strands?.update(direction.clone().multiplyScalar(gap*(1-ease((position-.25)/.53))),1-ease(position/.6),tendon)
  if(['p64','p68','p89'].includes(step))strands?.group.traverse(n=>{if(n instanceof THREE.Mesh){(n.material as THREE.Material).depthTest=!channels;n.renderOrder=channels?10:0}})
  if(['p33','p42','p46','p54','p62','p64','p68','p89'].includes(step)){
   const bounds=new THREE.Box3()
   for(const piece of selected){
    piece.object.updateMatrix();bounds.union(piece.bounds.clone().applyMatrix4(piece.object.matrix))
    const inspectable=step==='p68'?piece.part.label==='Thumb TP'||['Carpals','Touch carpals','Carpal core'].includes(piece.part.label):step==='p64'?piece.part.label.endsWith(' AP')||['Carpals','Touch carpals','Carpal core'].includes(piece.part.label):step!=='p89'||['Carpals','Touch carpals','Carpal core','Wrist frame'].includes(piece.part.label)
    fade(piece,channels&&!inspection&&inspectable?.32:1)
   }
   if(!inspection)strands?.group.traverse(n=>{if(n instanceof THREE.Mesh){n.geometry.computeBoundingBox();n.updateMatrix();bounds.union(n.geometry.boundingBox!.clone().applyMatrix4(n.matrix))}})
   group.position.copy(bounds.getCenter(new THREE.Vector3()).negate())
   const rotated=bounds.clone().translate(group.position).applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(view.rotation)).getSize(new THREE.Vector3())
   view.scale.setScalar(Math.min(340/rotated.y,400/rotated.x))
  }
 }
 return {view,parts:selected.map(p=>p.part.label),update,dispose:()=>{disposePieces(all);strands?.dispose();winding?.dispose()}}
}

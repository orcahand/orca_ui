import * as THREE from 'three'
import {cadPieces,disposePieces,fade,framed,nearest,type CadPiece} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'
import {jointForMotor,jointName,motorPieces,motorOwner} from './driveMap'

export const MOTOR_CHECK_IDS=Array.from({length:17},(_,i)=>i+1)
export const motorCheckName=(id:number,build:Build)=>id===1?'Wrist':jointName(jointForMotor(id,build)!)
export function motorCheckScene(bundle:Bundle,build:Build,id:number,mode:'hand'|'motor',jointColor?:string,scope?:{owners:string[];bare:boolean;hideSensors?:boolean;hideSkins?:boolean}) {
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),motors=motorPieces(pieces),motor=motors.get(id)!
 const joint=jointForMotor(id,build),name=joint?jointName(joint):'Wrist',segment=joint?.split('-')[1]
 const bodies=pieces.filter(p=>/^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label))
 const areas=(p:CadPiece)=>Object.keys(p.part.areas).filter(a=>p.part.areas[a].includes(p.name))
 const owner=(p:CadPiece)=>p.owner??(!bodies.includes(p)?nearest(bodies.filter(b=>areas(b).some(a=>areas(p).includes(a))),p.center)?.part.label:p.part.label)
 const downstream=segment?['DP','PP','AP','TP'].slice(0,['DP','PP','AP','TP'].indexOf(segment)+1).map(s=>`${name.split(' ')[0]} ${s}`):[]
 const bearings=pieces.filter(p=>p.part.label.startsWith('Bearing')&&(id===1?p.part.label==='Bearing · 8 × 13 × 4':p.owner===name))
 if(bearings.length!==2)throw new Error(`Missing pivot for ${name}`)
 const pivot=bearings[0].center.clone().add(bearings[1].center).multiplyScalar(.5),axis=bearings[1].center.clone().sub(bearings[0].center).normalize()
 const moving=new THREE.Group();moving.position.copy(pivot);group.add(moving)
 const spindle=new THREE.Group(),spool=pieces.find(p=>p.part.label===(id===1?'Wrist pulley':'Bottom spool')&&(id===1||motorOwner(p,motors)===id))!
 const spindleAxis=id===1?new THREE.Vector3(1,0,0):new THREE.Vector3(0,0,1)
 spindle.position.copy(spool.center);group.add(spindle)
 const selected:CadPiece[]=[],movingNames:string[]=[]
 for(const p of pieces){
  const hand=areas(p).some(a=>['Fingers','Thumb','Carpals'].includes(a))
  if(mode==='hand'&&!hand&&!(jointColor&&id===1&&p.part.label==='Wrist frame'))continue
  if(scope?.hideSkins&&p.part.category==='Skins')continue
  if(scope?.hideSensors&&(p.part.label.includes('touch module')||(p.part.category==='Skins'&&/DP skin|Pinky touch skin/.test(p.part.label))))continue
  if(scope&&(!scope.owners.includes(owner(p)??'')||(scope.bare&&(p.part.category==='Skins'||p.part.label.includes('touch module')||(p.part.label.startsWith('Bearing')&&p.owner?.endsWith(' PP'))))))continue
  if(mode==='motor'&&!(id===1?['Dynamixel XC430 wrist motor','Wrist motor adapter','Wrist pulley','Pin · 4 × 10'].includes(p.part.label):motorOwner(p,motors)===id&&['Dynamixel XC330 motor','Bottom spool','Top spool / tensioner','Ratchet','Spool cover','Spool ORCA insert','M2 × 4 socket screw','M2.5 × 8 socket screw'].includes(p.part.label)))continue
  selected.push(p)
  const active=mode==='hand'&&hand&&(id===1||downstream.includes(owner(p)??''))
  const rotates=mode==='motor'&&p!==motor
  if(active){moving.add(p.object);p.object.position.sub(pivot);movingNames.push(p.part.label)}
  else if(rotates){spindle.add(p.object);p.object.position.sub(spool.center)}
  else group.add(p.object)
  fade(p,mode==='motor'||active?1:jointColor?.45:.16)
 }
 const marker=new THREE.Mesh(new THREE.SphereGeometry(mode==='motor'?1.8:1,20,12),new THREE.MeshStandardMaterial({color:'#27b7bf',emissive:'#16848b',emissiveIntensity:.35}))
 if(mode==='motor'){marker.position.set(id===1?2:8,id===1?8:0,id===1?0:Math.sign(spool.center.z)*9);spindle.add(marker)}
 const jointRing=jointColor?new THREE.Mesh(new THREE.TorusGeometry(Math.max(7,bearings[0].center.distanceTo(bearings[1].center)/2+3),1.1,12,64),new THREE.MeshBasicMaterial({color:jointColor,depthTest:false,transparent:true,opacity:.9})):null
 if(jointRing){jointRing.position.copy(pivot);jointRing.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),axis);jointRing.renderOrder=10;group.add(jointRing)}
 const view=framed(group,build,mode==='hand'?350:240,mode==='hand'?430:320)
 if(mode==='motor'){view.rotation.y=id===1?-1.2:(spool.center.z<0?Math.PI-.35:.35);view.rotation.x=.2}
 const finger=name.split(' ')[0],tip=pieces.find(p=>p.part.label===`${finger} DP`),base=pieces.find(p=>p.part.label===`${finger} AP`),middle=pieces.find(p=>p.part.label==='Middle AP')!,pinky=pieces.find(p=>p.part.label==='Pinky AP')!
 const away=(finger==='Middle'?pinky:base)?.center.clone().sub(middle.center),spreadSign=tip&&away?(Math.sign(axis.clone().cross(tip.center.clone().sub(pivot)).dot(away))||1):1
 const flexPoint=pieces.find(p=>id===1?['Carpals','Touch carpals'].includes(p.part.label):p.part.label===name)?.center??pivot
 const hingeSign=axis.clone().cross(flexPoint.clone().sub(pivot)).z>0?-1:1
 const sign=hingeSign*(finger==='Thumb'&&(segment==='DP'||segment==='PP')?-1:1)
 const index=pieces.find(p=>p.part.label==='Index AP')!,towardPinkySign=tip?(Math.sign(axis.clone().cross(tip.center.clone().sub(pivot)).dot(pinky.center.clone().sub(index.center)))||1):1
 return {view,pivot,axis,sign,spreadSign,towardPinkySign,setAngle:(angle:number)=>moving.quaternion.setFromAxisAngle(axis,angle),movingNames,parts:selected.map(p=>p.part.label),update:(phase:number)=>{
  const cycle=Math.sin(phase*Math.PI*2),bend=(1-Math.cos(phase*Math.PI*2))/2
  moving.quaternion.setFromAxisAngle(axis,(segment==='AP'||id===1?cycle*.22:bend*.6)*sign)
  spindle.quaternion.setFromAxisAngle(spindleAxis,(segment==='AP'||id===1?cycle:bend)*.85)
 },dispose:()=>{disposePieces(pieces);marker.geometry.dispose();marker.material.dispose();jointRing?.geometry.dispose();jointRing?.material.dispose()}}
}

import * as THREE from 'three'
import {cadPieces,disposePieces,fade,framed,nearest,type CadPiece} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'
export type CadDetail={title:string;fixed:string[];moving:string[];caption:string;motorSpecific?:boolean}
export const CAD_DETAILS:Record<string,CadDetail>={
 'finishing-pp':{title:'Fit the skins and PP bearings',fixed:['Index DP','Index PP'],moving:['Index DP skin','Index PP skin','Bearing · 4 × 8 × 3','Bearing · 4 × 8 × 2','Middle / ring / index touch module'],caption:'Slide the DP skin over the fingertip and down. Slide the PP skin from its base upward toward the fingertip. Keep the tendons clear, then seat both PP bearings.'},
 p46:{title:'Fit the thumb skins and PP bearings',fixed:['Thumb DP','Thumb PP'],moving:['Thumb DP skin','Thumb PP skin','Bearing · 4 × 8 × 3','Bearing · 4 × 8 × 2','Thumb touch module'],caption:'Slide the DP skin over the fingertip and down. Slide the PP skin from its base toward the fingertip, then seat the PP bearings.'},
 p73:{title:'Finish the carpal assembly',fixed:['Carpals','Touch carpals','Carpal core'],moving:['Palm skin','Pin · 3 × 50','Carpal pulley','Bearing · 8 × 13 × 4'],caption:'Fit the palm skin, two long pins, toothed carpal pulley and two wrist bearings. The carpal pulley is the wrist gear on the hand: its teeth engage the belt; the motor pulley is fitted later.'},
 p98:{title:'Seat the connector PCBs',fixed:['Motor tower'],moving:['Motor connector PCB'],caption:'Twelve connector PCBs bridge the sixteen motor positions. Inspect their orientation before seating the motors.',motorSpecific:true},
 p127:{title:'Secure the four spool holders',fixed:['Motor tower'],moving:['Metal spool holder','M3 × 14 socket screw','M3 hex nut'],caption:'Fit the four nuts in the inside-bottom tower slots, slide in the four holders, then secure their screws.',motorSpecific:true},
 p129:{title:'Match the tower and wrist magnet seats',fixed:['Motor tower','Wrist frame'],moving:['Magnet · 5 × 3 mm'],caption:'Four tower magnets and four wrist magnets. Check mating polarity before applying glue.'},
 p139:{title:'Your assembled hand',fixed:[],moving:[],caption:'Rotate the completed assembly to review the palm, dorsum and wrist before tensioning.'},
}
export function cadDetailSpec(build:Build,step:string):CadDetail {
 const spec=CAD_DETAILS[step]
 if(build.version!=='touch'||!['finishing-pp','p46'].includes(step))return spec
 return {...spec,title:step==='p46'?'Fit the thumb PP skin and bearings':'Fit the PP skin and bearings',
  moving:spec.moving.filter(label=>!label.includes('touch module')&&!label.includes('DP skin')),
  caption:'Fit the PP skin and bearings. Leave DP bare; fit the Touch sensor after assembly, just before tensioning.'}
}
export function cadDetailScene(bundle:Bundle,build:Build,step:string){
 const skinStep=['finishing-pp','p46'].includes(step),finger=step==='p46'?'Thumb':'Index'
 const spec=cadDetailSpec(build,step),pieces=cadPieces(bundle,build),group=new THREE.Group()
 const fixed=pieces.filter(p=>spec.fixed.includes(p.part.label)||(skinStep&&p.part.label.startsWith('Bearing')&&p.owner===`${finger} DP`)),center=new THREE.Box3();fixed.forEach(p=>center.union(p.bounds));const anchor=center.isEmpty()?new THREE.Vector3():center.getCenter(new THREE.Vector3())
 const screws=pieces.filter(p=>p.part.label==='M3 × 14 socket screw')
 const moving=pieces.filter(p=>spec.moving.includes(p.part.label)).filter(p=>!skinStep||(p.part.label.startsWith('Bearing')?p.owner===`${finger} PP`:p.part.label.includes('touch module')&&step==='finishing-pp'?nearest(pieces.filter(b=>/^(Index|Middle|Ring) DP$/.test(b.part.label)),p.center)?.part.label==='Index DP':true)).filter(p=>step!=='p127'||p.part.label!=='M3 hex nut'||screws.some(s=>s.center.distanceTo(p.center)<25))
 const selected=step==='p139'?pieces.filter(p=>p.part.category!=='Tendons'&&!p.part.label.includes('(optional)')&&!(build.version==='touch'&&p.part.category==='Skins'&&/DP skin|Pinky touch skin/.test(p.part.label))):[...fixed,...moving]
 const offsets=new Map<CadPiece,THREE.Vector3>()
 for(const p of selected){group.add(p.object);if(!moving.includes(p))continue
  let direction=p.center.clone().sub(anchor).normalize()
  if(skinStep){
   const dp=pieces.filter(b=>b.owner===`${finger} DP`&&b.part.label.startsWith('Bearing')),pp=pieces.filter(b=>b.owner===`${finger} PP`&&b.part.label.startsWith('Bearing'))
   const mean=(bs:CadPiece[])=>bs.reduce((v,b)=>v.add(b.center),new THREE.Vector3()).multiplyScalar(1/bs.length)
   direction=p.part.label.includes('DP skin')?p.center.clone().sub(mean(dp)).normalize():mean(dp).sub(mean(pp)).normalize().multiplyScalar(p.part.label.includes('PP skin')?-1:1)
  }
  if(step==='p73'&&p.part.label==='Palm skin')direction=new THREE.Vector3(0,0,-1)
  if(step==='p73'&&p.part.label==='Carpal pulley')direction=new THREE.Vector3(1,0,0)
  if(step==='p98')direction=new THREE.Vector3(0,0,Math.sign(p.center.z))
  if(step==='p127'&&p.part.label==='Metal spool holder')direction=new THREE.Vector3(0,.5,Math.sign(p.center.z)).normalize()
  if(p.part.category==='Standard components'){
   direction=p.axis.clone();if(direction.dot(p.center.clone().sub(anchor))<0)direction.negate()
  }
  if(step==='p129'){
   const size=p.bounds.getSize(new THREE.Vector3()).toArray(),axis=size.indexOf(Math.min(...size));direction=new THREE.Vector3().setComponent(axis,axis===1?-1:Math.sign(p.center.x-anchor.x))
  }
  if(step==='p127'&&p.part.label==='M3 hex nut'){const screw=nearest(screws,p.center);direction=screw.axis.clone();if(direction.dot(p.center.clone().sub(screw.center))<0)direction.negate()}
  offsets.set(p,direction.multiplyScalar(skinStep&&p.part.category==='Skins'?50:skinStep?18:step==='p73'?28:32));p.object.position.copy(offsets.get(p)!)
 }
 const view=framed(group,build,340,530)
 const labels=[...new Set(moving.map(p=>p.part.label))]
 return {view,parts:selected.map(p=>p.part.label),labels,counts:labels.map(label=>moving.filter(p=>p.part.label===label).length),update:(amount:number,highlight:string)=>{
  for(const p of selected){p.object.position.copy(offsets.get(p)??new THREE.Vector3()).multiplyScalar(amount);fade(p,highlight?(p.part.label===highlight?1:.18):1)}
 },dispose:()=>disposePieces(pieces)}
}

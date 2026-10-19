import * as THREE from 'three'
import {cadPieces,disposePieces,fade,framed,nearest,type CadPiece} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'
export type CadDetail={title:string;fixed:string[];moving:string[];caption:string;motorSpecific?:boolean}
export const THUMB_PARTS=[
 {label:'Thumb DP',short:'DP',name:'Distal phalanx',color:'#2879cf'},
 {label:'Thumb PP',short:'PP',name:'Proximal phalanx',color:'#d77818'},
 {label:'Thumb AP',short:'AP',name:'Abduction phalanx',color:'#9853cb'},
 {label:'Thumb TP',short:'TP',name:'Thumb phalanx',color:'#168b79'},
]
export const CAD_DETAILS:Record<string,CadDetail>={
 'finishing-pp':{title:'Seat the finger skins',fixed:['Index DP','Index PP','Index AP','Index PP skin'],moving:['Index DP skin'],caption:'The PP skin is already fitted. Seat the DP skin where used, then check clearance at both joints.'},
 'pp-ready':{title:'Prepare the PP skin and bearings',fixed:['Index PP'],moving:['Index PP skin','Bearing · 4 × 8 × 3','Bearing · 4 × 8 × 2'],caption:'Slide the PP skin from the open base toward the fingertip, then press both PP bearings into their pockets with your fingers.'},
 'thumb-parts':{title:'Thumb parts (DP, PP, AP and TP)',fixed:['Thumb DP','Thumb PP','Thumb AP','Thumb TP'],moving:[],caption:'Identify the four thumb segments before preparation.'},
 'thumb-dp':{title:'Thumb DP bearings',fixed:['Thumb DP'],moving:['Bearing · 4 × 8 × 3'],caption:'Seat the tendon first, then press a bearing into each side.'},
 'thumb-pp':{title:'Thumb PP guide pins',fixed:['Thumb PP'],moving:['Pin · 2 × 8','Pin · 2 × 6'],caption:'Fit the middle and lower guide pins. The upper pin goes in after DP and PP are joined.'},
 'thumb-pp-ready':{title:'Prepare the thumb PP skin and bearings',fixed:['Thumb PP'],moving:['Thumb PP skin','Bearing · 4 × 8 × 3','Bearing · 4 × 8 × 2'],caption:'Slide the PP skin on from the base, then seat both PP bearings.'},
 'thumb-tp-pins':{title:'Thumb TP guide pins',fixed:['Thumb TP'],moving:['Pin · 2 × 30'],caption:'Press both long pins fully into their shaft slots.'},
 'thumb-skins':{title:'Seat the thumb skins',fixed:['Thumb DP','Thumb PP','Thumb AP','Thumb TP','Thumb PP skin'],moving:['Thumb DP skin'],caption:'Seat the DP skin where used; the PP skin is already fitted.'},
 'thumb-test':{title:'Inspect the assembled thumb',fixed:['Thumb DP','Thumb PP','Thumb AP','Thumb TP','Thumb PP skin','Thumb DP skin'],moving:[],caption:'Check all eight tendon movements on the physical thumb.'},
 p73:{title:'Finish the carpal assembly',fixed:['Carpals','Touch carpals','Carpal core'],moving:['Palm skin','Pin · 3 × 50','Carpal pulley','Bearing · 8 × 13 × 4'],caption:'Fit the palm skin, two long pins, toothed carpal pulley and two wrist bearings. The carpal pulley is the wrist gear on the hand: its teeth engage the belt; the motor pulley is fitted later.'},
 p98:{title:'Seat the connector PCBs',fixed:['Motor tower'],moving:['Motor connector PCB'],caption:'Twelve connector PCBs bridge the sixteen motor positions. Inspect their orientation before seating the motors.',motorSpecific:true},
 p127:{title:'Secure the four spool holders',fixed:['Motor tower'],moving:['Metal spool holder','M3 × 14 socket screw','M3 hex nut'],caption:'Fit the four nuts in the inside-bottom tower slots, slide in the four holders, then secure their screws.',motorSpecific:true},
 p129:{title:'Match the tower and wrist magnet seats',fixed:['Motor tower','Wrist frame'],moving:['Magnet · 5 × 3 mm'],caption:'Four tower magnets and four wrist magnets. Check mating polarity before applying glue.'},
 p139:{title:'Your assembled hand',fixed:[],moving:[],caption:'Rotate the completed assembly to review the palm, dorsum and wrist before tensioning.'},
}
export function cadDetailSpec(build:Build,step:string):CadDetail {
 const spec=CAD_DETAILS[step]
 if(build.version!=='touch')return spec
 if(['pp-ready','thumb-pp-ready'].includes(step))return {...spec,title:'Fit the PP bearings',moving:spec.moving.filter(label=>!label.includes('skin')),caption:'Press both PP bearings into their pockets.'}
 if(step==='thumb-test')return {...spec,fixed:spec.fixed.filter(label=>!label.includes('skin'))}
 return spec
}
export function cadDetailScene(bundle:Bundle,build:Build,step:string){
 const skinStep=['pp-ready','finishing-pp','thumb-pp-ready','thumb-skins'].includes(step),finger=step.startsWith('thumb-')?'Thumb':'Index'
 const spec=cadDetailSpec(build,step),pieces=cadPieces(bundle,build),group=new THREE.Group()
 const fixed=pieces.filter(p=>spec.fixed.includes(p.part.label)||(skinStep&&!['pp-ready','thumb-pp-ready'].includes(step)&&p.part.label.startsWith('Bearing')&&(p.owner===`${finger} DP`||['finishing-pp','thumb-skins'].includes(step)&&[`${finger} PP`,`${finger} AP`].includes(p.owner??'')))),center=new THREE.Box3();fixed.forEach(p=>center.union(p.bounds));const anchor=center.isEmpty()?new THREE.Vector3():center.getCenter(new THREE.Vector3())
 const screws=pieces.filter(p=>p.part.label==='M3 × 14 socket screw')
 const thumbDp=pieces.find(p=>p.part.label==='Thumb DP')!
 const thumbTp=pieces.find(p=>p.part.label==='Thumb TP')!
 const thumbPp=pieces.find(p=>p.part.label==='Thumb PP')!
 const inPp=(p:CadPiece)=>thumbPp.bounds.clone().expandByScalar(1).containsPoint(p.center)
 const lowerPin=pieces.filter(p=>p.part.label==='Pin · 2 × 6'&&inPp(p)).sort((a,b)=>b.center.distanceToSquared(thumbDp.center)-a.center.distanceToSquared(thumbDp.center))[0]
 const detailPart=(p:CadPiece)=>step==='thumb-dp'?p.owner==='Thumb DP':step==='thumb-pp'?(inPp(p)&&(p.part.label==='Pin · 2 × 8'||p===lowerPin)):step==='thumb-tp-pins'?thumbTp.bounds.clone().expandByScalar(1).containsPoint(p.center):true
 const moving=pieces.filter(p=>spec.moving.includes(p.part.label)&&detailPart(p)).filter(p=>!skinStep||(p.part.label.startsWith('Bearing')?p.owner===`${finger} PP`:p.part.label.includes('touch module')&&step==='finishing-pp'?nearest(pieces.filter(b=>/^(Index|Middle|Ring) DP$/.test(b.part.label)),p.center)?.part.label==='Index DP':true)).filter(p=>step!=='p127'||p.part.label!=='M3 hex nut'||screws.some(s=>s.center.distanceTo(p.center)<25))
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
  for(const p of selected){p.object.position.copy(offsets.get(p)??new THREE.Vector3()).multiplyScalar(amount);fade(p,highlight?(p.part.label===highlight?1:.18):1,step==='thumb-parts'?THUMB_PARTS.find(part=>part.label===p.part.label)?.color:undefined)}
 },dispose:()=>disposePieces(pieces)}
}

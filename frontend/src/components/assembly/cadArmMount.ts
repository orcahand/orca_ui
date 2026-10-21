import * as THREE from 'three'
import {cadPieces, disposePieces, fade, nearest} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadArmMount(bundle:Bundle,build:Build,stage:'adapter'|'covers'|'alignment'){
  const pieces=cadPieces(bundle,build),group=new THREE.Group(),labels:{text:string;point:THREE.Vector3}[]=[]
  const plate=pieces.find(p=>p.part.label==='Arm mounting adapter (optional)')!
  const rods=pieces.filter(p=>p.part.label==='Arm mounting rod (optional)')
  const tower=pieces.find(p=>p.part.label==='Motor tower')!
  const covers=pieces.filter(p=>['Hull cover','Rear hull cover'].includes(p.part.label))
  const selected=stage==='covers'
    ?pieces.filter(p=>p.part.areas.Tower?.includes(p.name)&&!p.part.label.startsWith('Arm mounting'))
    :[plate,...rods,...(stage==='alignment'?[tower]:[])]
  for(const piece of selected){
    group.add(piece.object)
    if(stage==='adapter'&&rods.includes(piece))piece.object.position.y=18
    if(stage==='alignment'&&piece===tower){piece.object.position.y=45;fade(piece,.22)}
    if(stage==='covers'){
      const cover=covers.includes(piece)?piece:piece.part.label==='OH control board'?covers.find(p=>p.part.label==='Rear hull cover'):piece.part.label==='Hull magnet'?nearest(covers,piece.center):undefined
      if(cover)piece.object.position.z=Math.sign(cover.center.z)*55
    }
  }
  function label(text:string,piece:typeof plate){
    if(!piece)return
    // Pick a surface point, rather than the empty centre of the adapter bore.
    let point=piece.center.clone(),distance=Infinity
    piece.object.updateMatrixWorld(true)
    piece.object.traverse(n=>{if(n instanceof THREE.Mesh){const positions=n.geometry.getAttribute('position');for(let i=0;i<positions.count;i++){const candidate=new THREE.Vector3().fromBufferAttribute(positions,i).applyMatrix4(n.matrixWorld),d=candidate.distanceToSquared(piece.center.clone().add(piece.object.position));if(d<distance){distance=d;point=candidate}}}})
    labels.push({text,point})
  }
  if(stage==='covers'){
    covers.forEach(p=>label(p.part.label==='Rear hull cover'?'Rear hull + board':'Hull cover',p))
  }else{
    label('Adapter plate',plate);label('Mounting rods · ×2',rods[0])
    if(stage==='alignment')label('Motor tower',tower)
  }
  return {group,labels,direction:new THREE.Vector3(1,.7,1),...(stage==='alignment'?{focus:new THREE.Box3().setFromObject(group)}:{}),dispose:()=>disposePieces(pieces)}
}

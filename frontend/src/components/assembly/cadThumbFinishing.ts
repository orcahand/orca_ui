import * as THREE from 'three'
import {cadKey,cadPieces,disposePieces,fade} from './cadScene'
import {thumbTpStrands} from './thumbTpStrands'
import frames from './thumbTpFrames.json'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadThumbFinishing(bundle:Bundle,build:Build,kind:'pins'|'bearings'){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),tp=pieces.find(p=>p.part.label==='Thumb TP')!
 const ap=pieces.find(p=>p.part.label==='Thumb AP')!,frame=frames[cadKey(build)]
 const axes=frame.basis.map(p=>new THREE.Vector3().fromArray(p))
 const pins=pieces.filter(p=>p.part.label==='Pin · 2 × 30'&&tp.bounds.clone().expandByScalar(1).containsPoint(p.center))
 const bearings=pieces.filter(p=>p.part.label.startsWith('Bearing')&&p.owner==='Thumb AP')
 if(pins.length!==2||bearings.length!==2)throw new Error('Expected two TP guide pins and two AP bearings')
 group.add(tp.object,ap.object,...pins.map(p=>p.object))
 fade(ap,.18);fade(tp,kind==='pins'?.28:.65)
 if(kind==='bearings')group.add(...bearings.map(p=>p.object))
 const strands=thumbTpStrands(build,pieces);strands.update(new THREE.Vector3(),0,-1);group.add(strands.group)
 const focus=tp.bounds.clone().expandByScalar(5)
 const labels=kind==='pins'?pins.map((p,i)=>({text:`Guide pin ${i+1} · 2 × 30`,point:p.center.clone()})):
  bearings.map((p,i)=>({text:p.part.label.replace('Bearing',`Bearing ${i+1}`),point:p.center.clone()}))
 return {group,labels,focus,direction:axes[kind==='pins'?1:0].clone().multiplyScalar(kind==='pins'?1:-1).addScaledVector(axes[2],kind==='pins'?1.2:.3).normalize(),up:axes[2],dispose:()=>{disposePieces(pieces);strands.dispose()}}
}

import * as THREE from 'three'
import { assemblyScene } from './assemblyScene'
import { cadDetailScene } from './cadDetails'
import frames from './jointFrames.json'
import { cadKey, cadPieces, disposePieces, nearest } from './cadScene'
import { ChannelCurve } from './channelStrands'
import conduits from './conduitRoutes.json'
import type { Bundle } from './cadAssets'
import type { Build } from './buildContent'

import {tubePullScene} from './tubePullScene'
import {cadRouteFace} from './cadRouteFace'
import {cadRoutingReference} from './cadRoutingReferences'
import {cadJointPreparation} from './cadJointPreparation'
import {cadWristPreparation} from './cadWristPreparation'
import {cadAnchorPreparation} from './cadAnchorPreparation'
import {cadApAnchorPreparation} from './cadApAnchorPreparation'
import {cadTpAnchorPreparation} from './cadTpAnchorPreparation'
import {cadThumbFinishing} from './cadThumbFinishing'
import {cadWristCrossing} from './cadWristCrossing'
import {cadSpoolPreparation} from './cadSpoolPreparation'
import {cadArmMount} from './cadArmMount'
import {cadTowerWiring} from './cadTowerWiring'
import type { Recipe } from './cadIllustrations'

// These scenes are used by the offline renderer, not mounted by the walkthrough.
export function illustrationScene(bundle:Bundle,build:Build,recipe:Recipe){
  if(recipe.file==='thumb-pp-part'){
    const pieces=cadPieces(bundle,build),group=new THREE.Group(),frame=frames[cadKey(build)].Thumb
    group.add(pieces.find(p=>p.part.label==='Thumb PP')!.object)
    return {group,labels:[],direction:new THREE.Vector3().fromArray(frame.y).negate().addScaledVector(new THREE.Vector3().fromArray(frame.x),.4),up:new THREE.Vector3().fromArray(frame.z),dispose:()=>disposePieces(pieces)}
  }
  if(recipe.towerWiring)return cadTowerWiring(bundle,build)
  if(recipe.armMount)return cadArmMount(bundle,build,recipe.armMount)
  if(recipe.spoolPreparation)return cadSpoolPreparation(bundle,build,recipe.spoolPreparation)
  if(recipe.wristCrossing)return cadWristCrossing(bundle,build)
  if(recipe.thumbFinishing)return cadThumbFinishing(bundle,build,recipe.thumbFinishing)
  if(recipe.tpAnchorPreparation)return cadTpAnchorPreparation(bundle,build,recipe.tpAnchorPreparation)
  if(recipe.apAnchorPreparation)return cadApAnchorPreparation(bundle,build,recipe.apAnchorPreparation,recipe.thumbAnchor)
  if(recipe.anchorPreparation)return cadAnchorPreparation(bundle,build,recipe.anchorPreparation,recipe.thumbAnchor)
  if(recipe.wristPreparation)return cadWristPreparation(bundle,build,recipe.wristPreparation)
  if(recipe.jointPreparation)return cadJointPreparation(bundle,build,recipe.jointPreparation)
  if(recipe.routingReference)return cadRoutingReference(bundle,build,recipe.routingReference)
  if(recipe.tubePull!==undefined)return tubePullScene(bundle,build,recipe.tubePull)
  if(recipe.routeFace)return cadRouteFace(bundle,build,recipe.step,recipe.routeFace)
  if(recipe.scene){
    const model=recipe.scene==='motion'?assemblyScene(bundle,build,recipe.step):cadDetailScene(bundle,build,recipe.step)
    if(recipe.scene==='motion')(model as ReturnType<typeof assemblyScene>).update(recipe.position??0,0)
    else (model as ReturnType<typeof cadDetailScene>).update(recipe.position??0,'')
    if(['panel-092-1','panel-092-2'].includes(recipe.file))for(const part of bundle.inventory.parts.filter(p=>['Motor tower','M4 × 10 socket screw','M4 hex nut'].includes(p.label)))for(const name of part.nodes){const object=model.view.getObjectByName(name);if(object)object.visible=false}
    if(recipe.step==='p123')model.view.traverse(n=>{if(n instanceof THREE.Mesh&&(n.material as THREE.MeshStandardMaterial).opacity<.3)n.visible=false})
    if(recipe.step==='p126')model.view.traverse(n=>{if(n instanceof THREE.Mesh){const m=n.material as THREE.MeshStandardMaterial;m.opacity=1;m.transparent=false;m.depthWrite=true}})
    return {group:model.view,labels:[] as {text:string;point:THREE.Vector3}[],direction:new THREE.Vector3(...(recipe.view??[0,0,1])),dispose:model.dispose}
  }
  const pieces=cadPieces(bundle,build),group=new THREE.Group(),extra:THREE.Mesh[]=[]
  let selected=pieces.filter(p=>recipe.parts?.includes(p.part.label))
  if(recipe.owner?.startsWith('Index')){
    const bodies=pieces.filter(p=>/^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label))
    selected=selected.concat(pieces.filter(p=>(recipe.step==='p33'?selected[0].bounds.clone().expandByScalar(1).containsPoint(p.center):(p.owner===recipe.owner||(!p.owner&&nearest(bodies,p.center)?.part.label===recipe.owner)))&&p.part.category==='Standard components'&&
      (recipe.step==='p29'?p.part.label.startsWith('Bearing'):p.part.label.startsWith('Pin'))))
    if(recipe.step==='p33'){
      const long=selected.find(p=>p.part.label==='Pin · 2 × 8')
      const short=selected.filter(p=>p.part.label==='Pin · 2 × 6')
      // The lower pin is farther from the DP hinge than the upper pin.
      const dp=pieces.find(p=>p.part.label==='Index DP')!
      const lower=[...short].sort((a,b)=>b.center.distanceTo(dp.center)-a.center.distanceTo(dp.center))[0]
      selected=selected.filter(p=>p.part.label==='Index PP'||p===long||p===lower)
    }
  }
  if(recipe.owner==='wrist-pulley')selected.push(nearest(pieces.filter(p=>p.part.label.startsWith('Bearing')),selected[0].center))
  if(recipe.owner==='hull'){
    const covers=pieces.filter(p=>['Hull cover','Rear hull cover'].includes(p.part.label))
    selected=selected.filter(p=>p.part.label!=='Hull magnet'||nearest(covers,p.center).part.label==='Hull cover')
  }
  if(recipe.step==='p93')selected=selected.filter(p=>p.part.label!=='M3 hex nut'||p.center.y>-20)
  const structural=selected.filter(p=>p.part.category!=='Standard components')
  const center=new THREE.Box3();structural.forEach(p=>center.union(p.bounds));const origin=center.getCenter(new THREE.Vector3())
  for(const p of selected){
    group.add(p.object)
    if(p.part.label==='Carpal core')p.object.traverse(n=>{if(n instanceof THREE.Mesh){const m=n.material as THREE.MeshStandardMaterial;m.polygonOffset=true;m.polygonOffsetFactor=2;m.polygonOffsetUnits=2}})
    if(recipe.owner==='hull'&&p.part.label==='Hull cover')p.object.traverse(n=>{if(n instanceof THREE.Mesh){const m=n.material as THREE.MeshStandardMaterial;m.opacity=.25;m.transparent=true;m.depthWrite=false}})
    if(recipe.explode&&(p.part.category==='Standard components'||p.part.label==='Wrist motor adapter')){
      const axis=p.part.label==='Wrist motor adapter'?new THREE.Vector3(1,0,0):p.axis.clone();if(axis.dot(p.center.clone().sub(origin))<0)axis.negate()
      p.object.position.copy(axis).multiplyScalar(recipe.explode)
    }
  }
  if(recipe.liners){
    const paths=conduits[`${build.version==='touch'?'touch':'base'}-${build.side}`][recipe.liners]
    for(const path of paths){
      const points=path.map(p=>new THREE.Vector3().fromArray(p))
      points[0].add(points[0].clone().sub(points[1]).normalize())
      points[points.length-1].add(points.at(-1)!.clone().sub(points.at(-2)!).normalize())
      const mesh=new THREE.Mesh(new THREE.TubeGeometry(new ChannelCurve(points),Math.max(80,points.length),.73,12,false),new THREE.MeshStandardMaterial({color:'#ded9bb',roughness:.65}))
      group.add(mesh);extra.push(mesh)
    }
  }
  const labels=(recipe.labelParts??[]).flatMap(label=>{
    const p=selected.find(p=>p.part.label===label)
    return p?[{text:label,point:p.center.clone().add(p.object.position)}]:[]
  })
  return {group,labels,direction:new THREE.Vector3(...(recipe.view??[.6,.4,-1])),dispose:()=>{disposePieces(pieces);extra.forEach(p=>{p.geometry.dispose();(p.material as THREE.Material).dispose()})}}
}

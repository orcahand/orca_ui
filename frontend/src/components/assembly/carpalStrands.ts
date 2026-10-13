import * as THREE from 'three'
import fingerRoutes from './fingerCarpalRoutes.json'
import thumbRoutes from './thumbCarpalRoutes.json'
import {ChannelCurve} from './channelStrands'
import {cadKey,TENDON_COLORS,type CadPiece} from './cadScene'
import type {Build} from './buildContent'

const kinds=['AP-p','PP-ext','DP-ext','DP-flex','PP-flex','AP-t']
const colors=['#d99d54','#81bb50','#d3bd50','#ae86eb','#f26962','#29bfcb']
export function carpalStrands(build:Build,pieces:CadPiece[],thumb=false){
 const group=new THREE.Group(),carpals=pieces.find(p=>p.part.label===(build.version==='touch'?'Touch carpals':'Carpals'))!
 const paths=(thumb?thumbRoutes:fingerRoutes)[cadKey(build)].map(path=>{
  const selection=thumb?path.index-8:kinds.indexOf(path.kind),material=new THREE.MeshBasicMaterial({color:thumb?TENDON_COLORS[selection]:colors[selection],transparent:true})
  const mesh=new THREE.Mesh(new THREE.BufferGeometry(),material);group.add(mesh)
  return {moving:path.moving.map(p=>new THREE.Vector3().fromArray(p)),fixed:path.fixed.map(p=>new THREE.Vector3().fromArray(p)),ap:pieces.find(p=>p.part.label===`${path.finger} ${thumb?'TP':'AP'}`)!,selection,material,mesh}
 })
 function update(_displacement:THREE.Vector3,_slack:number,selected:number){
  for(const path of paths){
   const transform=(points:THREE.Vector3[],piece:CadPiece)=>points.map(p=>p.clone().applyQuaternion(piece.object.quaternion).add(piece.object.position))
   path.mesh.geometry.dispose();path.mesh.geometry=new THREE.TubeGeometry(new ChannelCurve([...transform(path.moving,path.ap),...transform(path.fixed,carpals)]),thumb?1800:900,thumb?.14:.18,10,false)
   path.material.opacity=path.selection===selected?1:.8
  }
 }
 return {group,count:paths.length,update,dispose:()=>paths.forEach(p=>{p.mesh.geometry.dispose();p.material.dispose()})}
}

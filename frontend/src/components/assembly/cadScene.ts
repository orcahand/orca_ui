import * as THREE from 'three'
import geometry from './cadGeometry.json'
import {finishMaterial,type Bundle} from './cadAssets'
import type {Part} from './assemblyParts'
import type {Build} from './buildContent'
export type CadPiece={name:string;part:Part;object:THREE.Group;center:THREE.Vector3;axis:THREE.Vector3;bounds:THREE.Box3;owner?:string}
export const cadKey=(build:Build)=>`${build.version==='touch'?'touch':'base'}-${build.side}` as keyof typeof geometry
export function cadPieces(bundle:Bundle,build:Build):CadPiece[]{
 bundle.scene.updateMatrixWorld(true)
 const data=geometry[cadKey(build)] as Record<string,{center:number[];axis?:number[];path?:string}>
 const middleRing=new Map<string,string>()
 for(const branch of ['M','M (1)']){
  const bearings=Object.values(data).filter(d=>d.path?.split('/')[2].replace('-Touch','')===branch&&/I-AP/.test(d.path))
  if(!bearings.length)continue
  const center=bearings.reduce((v,d)=>v.add(new THREE.Vector3().fromArray(d.center)),new THREE.Vector3()).multiplyScalar(1/bearings.length)
  const candidates=bundle.inventory.parts.filter(p=>['Middle AP','Ring AP'].includes(p.label)).map(p=>({label:p.label.split(' ')[0],center:new THREE.Vector3().fromArray(data[p.nodes[0]].center)}))
  middleRing.set(branch,nearest(candidates,center).label)
 }
 return bundle.inventory.parts.flatMap(part=>part.nodes.flatMap(name=>{
  const original=bundle.scene.getObjectByName(name);if(!original)return []
  const object=new THREE.Group();object.name=name
  original.traverse(node=>{if(node instanceof THREE.Mesh){const mesh=new THREE.Mesh(node.geometry,finishMaterial(part,build,node.geometry));mesh.applyMatrix4(node.matrixWorld);object.add(mesh)}})
  const bounds=new THREE.Box3().setFromObject(object),center=data[name]?new THREE.Vector3().fromArray(data[name].center):bounds.getCenter(new THREE.Vector3())
  const axis=new THREE.Vector3().fromArray(data[name]?.axis??[0,0,1])
  const path=data[name]?.path?.split('/')??[],branch=(path[2]??'').replace('-Touch',''),finger=branch.startsWith('I-')?'Index':middleRing.has(branch)?middleRing.get(branch):branch==='P'?'Pinky':branch.startsWith('Thumb')?'Thumb':undefined
  const segment=path.slice(3,-1).reverse().map(s=>s.match(/(?:[IMPT]-(IP|DP|PP|AP|TP)|[RL]-T-(AP))/)?.slice(1).find(Boolean)).find(Boolean)
  const owner=finger&&segment?`${finger} ${segment==='IP'?'DP':segment}`:undefined
  return [{name,part,object,center,axis,bounds,owner}]
 }))
}
export function fade(piece:CadPiece,opacity:number,color?:string){piece.object.traverse(node=>{if(node instanceof THREE.Mesh){const m=node.material as THREE.MeshStandardMaterial;m.transparent=opacity<1;m.opacity=opacity;m.depthWrite=opacity>.8;if(color){m.color.set(color);m.emissive.set(color);m.emissiveIntensity=.14}}})}
export function disposePieces(pieces:CadPiece[]){pieces.forEach(p=>p.object.traverse(n=>{if(n instanceof THREE.Mesh)(n.material as THREE.Material).dispose()}))}
export function nearest<T extends {center:THREE.Vector3}>(items:T[],point:THREE.Vector3){return [...items].sort((a,b)=>a.center.distanceToSquared(point)-b.center.distanceToSquared(point))[0]}
export const ease=(x:number)=>{const t=THREE.MathUtils.clamp(x,0,1);return t*t*(3-2*t)}
export function framed(group:THREE.Group,build:Build,extent=310,maxWidth=400){
 const box=new THREE.Box3().setFromObject(group),center=box.getCenter(new THREE.Vector3());group.position.copy(center).negate()
 const view=new THREE.Group();view.add(group);view.rotation.set(.15,build.side==='right'?2.65:-2.65,0);const projected=new THREE.Box3().setFromObject(view).getSize(new THREE.Vector3());view.scale.setScalar(Math.min(extent/projected.y,maxWidth/projected.x));return view
}
export const TENDON_COLORS=['#0098be','#f17615','#d5a000','#893ee7','#29a34a','#e42b69','#1072e2','#cf562b']

import * as THREE from 'three'
import {cadPieces,disposePieces} from './cadScene'
import type {Bundle} from './cadAssets'
import type {Build} from './buildContent'

export function cadTowerWiring(bundle:Bundle,build:Build){
 const pieces=cadPieces(bundle,build),group=new THREE.Group(),wires:THREE.Mesh[]=[]
 const tower=pieces.find(p=>p.part.label==='Motor tower')!,fans=pieces.filter(p=>p.part.label==='Cooling fan')
 group.add(tower.object,...fans.map(p=>p.object))
 function wire(points:number[][],color:string){
  const path=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3().fromArray(p)),false,'centripetal')
  const mesh=new THREE.Mesh(new THREE.TubeGeometry(path,240,.4,16,false),new THREE.MeshStandardMaterial({color,roughness:.65}))
  group.add(mesh);wires.push(mesh)
 }
 // Short cable segments identify the measured slots; their ends are not connectors.
 for(const x of [-50,-48.7,-47.4])wire([[x,48,26.5],[x,39,26.5],[x,34,28],[x,32,33],[x,27,39],[x,12,42]],'#353d42')
 for(const [i,y] of [3,-3].entries())for(const [j,color] of ['#b94e43','#333c41'].entries()){
  const x=-49.2+i*2.6+j*1.2
  wire([[x,i===0?20:-19,26.5],[x,y,27],[x,y,31],[x,y-3,37],[x,y-18,42]],color)
 }
 const labels=[
  {text:'Motor lead (upper slot)',point:new THREE.Vector3(-48.7,32,33)},
  {text:'Fan leads (lower slot)',point:new THREE.Vector3(-47.3,0,31)},
 ]
 return {group,labels,direction:new THREE.Vector3(-1,.2,1),dispose:()=>{disposePieces(pieces);wires.forEach(w=>{w.geometry.dispose();(w.material as THREE.Material).dispose()})}}
}

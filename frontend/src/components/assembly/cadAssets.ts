import * as THREE from 'three'
import {fitBeltBetweenSleeves} from './beltGuideGeometry'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import type { Inventory, Part } from './assemblyParts'
import type { Build } from './buildContent'
export type Bundle={inventory:Inventory;scene:THREE.Group}
const bundles=new Map<string,Promise<Bundle>>()
export function loadBundle(key:string) {
  if(!/^(base|touch)-(left|right)-dynamixel$/.test(key))return Promise.reject(new Error('Unavailable configuration'))
  let request=bundles.get(key)
  if(!request){request=Promise.all([
    fetch(`./assembly/parts/${key}/inventory.json`).then(r=>{if(!r.ok||!r.headers.get('content-type')?.includes('json'))throw new Error('Unavailable');return r.json() as Promise<Inventory>}),
    new GLTFLoader().loadAsync(`./assembly/parts/${key}/assembly.glb`),
  ]).then(([inventory,gltf])=>{fitBeltBetweenSleeves(gltf.scene,inventory);return {inventory,scene:gltf.scene}});bundles.set(key,request);request.catch(()=>bundles.delete(key))}
  return request
}
export function finishMaterial(part:Part,build:Build,geometry?:THREE.BufferGeometry) {
  const skin=part.category==='Skins',metal=part.category==='Standard components'||part.label==='Metal spool holder',tendon=part.category==='Tendons'
  const boardColors=part.label==='OH control board'&&!!geometry?.getAttribute('color')
  return new THREE.MeshStandardMaterial({color:boardColors?'#ffffff':skin?(build.version==='base'?'#e9eded':'#161b20'):metal?'#b5bcc3':tendon?'#f5f6f2':/OH control board/.test(part.label)?'#171c1b':/board|PCB/.test(part.label)?'#171c1b':'#29333b',vertexColors:boardColors,roughness:skin?.76:metal?.3:.48,metalness:metal?.55:0})
}

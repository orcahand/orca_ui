import * as THREE from 'three'
import ranges from './modelJointRanges.json'
import frames from './livePoseFrames.json'
import type {Build} from './buildContent'

// Model limits come from public/assembly/movement/{left,right}/hand.urdf.
// Convert their absolute angles into rotations about the exported CAD bearing axis.
export function illustratedJointRange(build:Build,joint:string,axis:THREE.Vector3){
 const limits=(ranges[build.side] as Record<string,number[]>)[joint]
 const key=`${build.version==='touch'?'touch':'base'}-${build.side}` as keyof typeof frames
 const frame=(frames[key] as Record<string,{restDegrees:number;axis:number[]}>)[joint]
 if(!limits||!frame)throw new Error(`Missing illustrated joint range: ${key}/${joint}`)
 const alignment=Math.sign(axis.dot(new THREE.Vector3().fromArray(frame.axis)))
 if(!alignment)throw new Error(`Invalid bearing axis: ${key}/${joint}`)
 return {degrees:limits,angles:limits.map(deg=>THREE.MathUtils.degToRad(deg-frame.restDegrees)*alignment)}
}
export function rangeAngle(range:ReturnType<typeof illustratedJointRange>,phase:number,direction=1){
 const [low,high]=[...range.angles].sort((a,b)=>a-b)
 return THREE.MathUtils.lerp(direction>0?low:high,direction>0?high:low,THREE.MathUtils.clamp(phase,0,1))
}
export function fitIllustratedRange(scene:{view:THREE.Group;setAngle:(angle:number)=>void},range:ReturnType<typeof illustratedJointRange>,height=340,width=410){
 const bounds=new THREE.Box3()
 for(let i=0;i<=12;i++){scene.setAngle(rangeAngle(range,i/12));scene.view.updateMatrixWorld(true);bounds.union(new THREE.Box3().setFromObject(scene.view))}
 const size=bounds.getSize(new THREE.Vector3()),factor=Math.min(1,width/size.x,height/size.y)
 scene.view.scale.multiplyScalar(factor)
 scene.view.position.sub(bounds.getCenter(new THREE.Vector3()).multiplyScalar(factor))
 scene.setAngle(0)
}

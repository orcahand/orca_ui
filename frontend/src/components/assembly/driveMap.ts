import * as THREE from 'three'
import {nearest,type CadPiece} from './cadScene'
import type {Build} from './buildContent'
import {TENDONS} from './guide'
export const FINGER_NAMES:Record<string,string>={T:'Thumb',I:'Index',M:'Middle',R:'Ring',P:'Pinky'}
const right:Record<string,number>={'T-TP':17,'T-AP':14,'T-PP':15,'T-DP':16,'I-AP':4,'I-PP':3,'I-DP':2,'M-AP':5,'M-PP':10,'M-DP':9,'R-AP':6,'R-PP':7,'R-DP':8,'P-AP':13,'P-PP':12,'P-DP':11}
const left:Record<string,number>={'T-TP':10,'T-AP':13,'T-PP':12,'T-DP':11,'I-AP':7,'I-PP':8,'I-DP':9,'M-AP':6,'M-PP':17,'M-DP':2,'R-AP':5,'R-PP':4,'R-DP':3,'P-AP':14,'P-PP':15,'P-DP':16}
export const JOINTS=Object.keys(right)
export const jointName=(key:string)=>`${FINGER_NAMES[key[0]]} ${key.split('-')[1]}`
export const motorId=(joint:string,build:Build)=>(build.side==='left'?left:right)[joint]
export const jointForMotor=(id:number,build:Build)=>JOINTS.find(j=>motorId(j,build)===id)
export const jointTendons=(joint:string)=>TENDONS.map((name,index)=>({name,index})).filter(t=>t.name.startsWith(`${joint}-`))
export function motorPieces(pieces:CadPiece[]){
 const motors=pieces.filter(p=>p.part.label==='Dynamixel XC330 motor'),mean=motors.reduce((v,p)=>v.add(p.center),new THREE.Vector3()).multiplyScalar(1/motors.length)
 const result=new Map<number,CadPiece>()
 for(const x of [-1,1])for(const z of [-1,1]){
  const column=motors.filter(p=>Math.sign(p.center.x-mean.x)===x&&Math.sign(p.center.z-mean.z)===z).sort((a,b)=>b.center.y-a.center.y)
  column.forEach((p,row)=>result.set(z<0?(x<0?17-row:10+row):(x<0?2+row:9-row),p))
 }
 const wrist=pieces.find(p=>p.part.label==='Dynamixel XC430 wrist motor');if(wrist)result.set(1,wrist)
 return result
}
export function motorOwner(piece:CadPiece,motors:Map<number,CadPiece>){return [...motors.entries()].find(([,p])=>p===nearest([...motors.values()],piece.center))?.[0]}

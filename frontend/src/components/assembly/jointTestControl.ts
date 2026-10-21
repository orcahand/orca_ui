import type {HandInfo,StatusSnapshot,ControlState} from '../../api/types'
import type {Build} from './buildContent'
import {jointForMotor} from './driveMap'

export function testJoint(id:number,build:Build){
 if(id===1)return 'wrist'
 const [finger,part]=jointForMotor(id,build)!.split('-')
 const name=({T:'thumb',I:'index',M:'middle',R:'ring',P:'pinky'} as Record<string,string>)[finger]
 return `${name}_${part==='TP'?'cmc':part==='AP'?'abd':part==='PP'?'mcp':finger==='T'?'dip':'pip'}`
}

export function liveTestBlock(build:Build,info:HandInfo|null,status:StatusSnapshot|null,control:ControlState|null,ws:boolean){
 if(!ws)return 'Waiting for the console connection.'
 if(!info||!status?.capabilities?.motors||!['connected','degraded'].includes(status.state))return 'Connect and power the hand to begin.'
 const version=info.model_name.includes('full')?'full':info.model_name.includes('touch')?'touch':'base'
 if(info.side!==build.side||version!==build.version)return 'The connected hand does not match your selected build.'
 if(!info.mock&&info.model_name!==`orcahand${build.version==='base'?'':`-${build.version}`}-${build.side}`)return 'Select the matching V2 model in Setup before this test.'
 if(info.calibration.motors!==true||info.calibration.missing_anchors.length>0)return 'Complete tensioning and calibration in Setup, then return here.'
 if(!control||control.control_source!=='manual')return `Wait until ${control?.control_owner??'the current operation'} releases control.`
 if(control.direct_motor_mode)return 'Exit direct motor control before this test.'
 return null
}

export function testTarget(center:number,offset:number,rom:[number,number]){
 if(![center,offset,...rom].every(Number.isFinite)||rom[0]>=rom[1]||center<rom[0]||center>rom[1])return null
 return Math.max(rom[0],Math.min(rom[1],center+Math.max(-10,Math.min(10,offset))))
}

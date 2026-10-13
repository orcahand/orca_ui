import type {LatestFrames} from '../../state/streamStore'
import type {HandInfo,ControlState} from '../../api/types'
import type {Build} from './buildContent'

export function assemblyPose(build:Build,info:HandInfo|null,control:ControlState|null,connected:boolean,frames:LatestFrames){
 const version=info?.model_name.includes('full')?'full':info?.model_name.includes('touch')?'touch':'base'
 if(!connected||!info||info.side!==build.side||version!==build.version||info.calibration.motors!==true||info.calibration.needs_calibration)return null
 const pose:Record<string,number>={}
 for(const joint of info.joints){
  const reported=joint.encoder_backed?frames.joints.measured[joint.id]:control?.effective_pose_source==='target'?frames.joints.target[joint.id]:frames.joints.estimate[joint.id]
  const angle=Number.isFinite(reported)?reported:frames.joints.estimate[joint.id],rom=joint.rom_effective??joint.rom
  if(Number.isFinite(angle)&&rom.every(Number.isFinite)&&rom[0]<rom[1])pose[joint.id]=Math.max(rom[0],Math.min(rom[1],angle))
 }
 return pose
}

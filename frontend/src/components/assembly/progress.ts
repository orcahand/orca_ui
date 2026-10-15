import { FINGER_CHECKS } from './fingerMovements'
import { STEPS } from './guide'
import { FINAL_CHECKS, type Build, type FlashingMethod } from './buildContent'

export const PROGRESS_KEY = 'orca-ui.assembly.v2.1'
export type Progress = {
  current: string
  done: string[]
  tendons: number[]
  checks: string[]
  views: Record<string, string>
  build: Build
}
export const EMPTY_PROGRESS: Progress = { current: STEPS[0].id, done: [], tendons: [], checks: [], views: {'guide:revision':'assembly-v5','guide:feedback':'oct15-v1'}, build: { side: 'right', motor: 'dynamixel', version: 'base', audience: 'internal' } }
export function readProgress(): Progress {
  try {
    return validateProgress(JSON.parse(localStorage.getItem(PROGRESS_KEY) ?? 'null'))
  } catch { return structuredClone(EMPTY_PROGRESS) }
}
export function validateProgress(data: unknown): Progress {
  try {
    const parsed = data as Record<string, any>
    const progress = parseProgress(parsed)
    if(parsed?.views?.['guide:revision']!=='assembly-v5'){
      progress.done=progress.done.filter(id=>id!=='motor-check')
      progress.checks=progress.checks.filter(key=>!key.startsWith('motor-check:'))
    }
    if(!['assembly-v4','assembly-v5'].includes(parsed?.views?.['guide:revision'])){
      if(parsed?.done?.includes('p35'))progress.done.push('finishing-pp')
      if(!parsed?.done?.includes('p40'))progress.done=progress.done.filter(id=>id!=='p37')
    }
    if(!['assembly-v3','assembly-v4','assembly-v5'].includes(parsed?.views?.['guide:revision']) && !['p115','p117','p119'].every(id=>parsed?.done?.includes(id)))progress.done=progress.done.filter(id=>id!=='p115')
    progress.views['guide:revision']='assembly-v5'
    if(parsed?.views?.['guide:feedback']!=='oct15-v1'){
      const changed=['p15','p18','p46','p54','p62','p126','p139',...(progress.build.version==='touch'?['p1','p110','p154']:[])]
      progress.done=progress.done.filter(id=>!changed.includes(id))
      progress.checks=progress.checks.filter(key=>!changed.some(id=>key.startsWith(`${id}:`)))
    }
    progress.views['guide:feedback']='oct15-v1'
    if (!progress.checks.includes('p1:0') || !progress.checks.includes('p1:1')) progress.done = progress.done.filter(id => id !== 'p1')
    // Preserve a finger's completed six-tendon check when loading earlier progress.
    FINGER_CHECKS.forEach((_,i)=>{if(Array.from({length:6},(_,j)=>`p45:movement:${i*6+j}`).every(key=>progress.checks.includes(key))&&!progress.checks.includes(`p45:finger:${i}`))progress.checks.push(`p45:finger:${i}`)})
    progress.checks=progress.checks.filter(key=>!key.startsWith('p45:movement:'))
    progress.done=progress.done.filter(id=>id!=='p45')
    if (FINGER_CHECKS.every((_,i)=>progress.checks.includes(`p45:finger:${i}`))) progress.done.push('p45')
    if(progress.tendons.length!==32)progress.done=progress.done.filter(id=>id!=='p83')
    for(const id of ['p123','p126'])if(!Array.from({length:32},(_,i)=>`${id}:tendon:${i}`).every(key=>progress.checks.includes(key)))progress.done=progress.done.filter(done=>done!==id)
    if(!Array.from({length:17},(_,i)=>`motor-check:${i+1}`).every(key=>progress.checks.includes(key)))progress.done=progress.done.filter(id=>id!=='motor-check')
    if(!FINAL_CHECKS.every((_,i)=>progress.checks.includes(`p139:${i}`)))progress.done=progress.done.filter(id=>id!=='p139')
    return progress
  } catch { return structuredClone(EMPTY_PROGRESS) }
}
function parseProgress(data: Record<string, any>): Progress {
  try {
    if (!data || typeof data !== 'object') return structuredClone(EMPTY_PROGRESS)
    return {
      current: data.current==='p40'?'p37':data.current==='p97'?'p99':['p117','p119'].includes(data.current) ? 'p115' : STEPS.some(s => s.id === data.current) ? data.current : EMPTY_PROGRESS.current,
      done: Array.isArray(data.done) ? [...new Set<string>(data.done.filter((id: unknown) => STEPS.some(s => s.id === id)))] : [],
      tendons: Array.isArray(data.tendons) ? [...new Set<number>(data.tendons.filter((n: unknown) => typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < 32))] : [],
      checks: Array.isArray(data.checks) ? [...new Set<string>(data.checks.filter((s: unknown) => typeof s === 'string'))] : [],
      views: data.views && typeof data.views === 'object' && !Array.isArray(data.views) ? Object.fromEntries(Object.entries(data.views).filter(([, value]) => typeof value === 'string')) as Record<string,string> : {},
      build: { audience: data.build?.audience === 'external' ? 'external' : 'internal', side: data.build?.side === 'left' ? 'left' : 'right', motor: data.build?.motor === 'feetech' ? 'feetech' : 'dynamixel', version: data.build?.version === 'full' || data.build?.sensing === 'joint' ? 'full' : data.build?.version === 'touch' || data.build?.sensing === 'touch' ? 'touch' : 'base' },
    }
  } catch { return structuredClone(EMPTY_PROGRESS) }
}

export function flashingMethod(progress: Progress): FlashingMethod {
  return progress.views['flashing:method']==='firmware'||(!progress.views['flashing:method']&&['p150','p154'].includes(progress.current))?'firmware':'console'
}
export function changeBuildProgress(progress: Progress, value: Partial<Build>): Progress {
  const side=value.side!==undefined&&value.side!==progress.build.side
  const motor=value.motor!==undefined&&value.motor!==progress.build.motor
  const version=value.version!==undefined&&value.version!==progress.build.version
  const audience=value.audience!==undefined&&value.audience!==progress.build.audience
  if(!side&&!motor&&!version&&!audience)return progress
  const affected=STEPS.filter(s=>s.id==='p1'||
    ((side||version)&&s.chapter!=='Fundamentals')||
    (motor&&['Tower','Electronics','Motors','Spooling','Hull','Finish'].includes(s.chapter))||
    ((motor||audience)&&s.chapter.startsWith('Flashing'))).map(s=>s.id)
  return {...progress,build:{...progress.build,...value},done:progress.done.filter(id=>!affected.includes(id)),
    checks:progress.checks.filter(key=>!affected.some(id=>key.startsWith(`${id}:`))),
    tendons:side||version?[]:progress.tendons,
    views:side||version?{'guide:revision':'assembly-v5','guide:feedback':'oct15-v1','flashing:method':flashingMethod(progress)}:progress.views}
}

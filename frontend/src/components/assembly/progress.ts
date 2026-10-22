import { FINGER_CHECKS } from './fingerMovements'
import { STEPS } from './guide'
import { BASE_STEP_REDIRECTS, FINAL_CHECKS, type Build, type FlashingMethod } from './buildContent'
import { WEB_GUIDE } from './webMode'

export const PROGRESS_KEY = 'orca-ui.assembly.v2.1'
export type Progress = {
  current: string
  done: string[]
  tendons: number[]
  checks: string[]
  views: Record<string, string>
  build: Build
}
export const EMPTY_PROGRESS: Progress = { current: STEPS[0].id, done: [], tendons: [], checks: [], views: {'guide:revision':'assembly-v5','guide:feedback':'oct15-v1','guide:layout':'oct16-v1','guide:finger-layout':'parts-first-v1','guide:thumb-layout':'parts-first-v1','guide:thumb-cables':'oct18-v1'}, build: { side: 'right', motor: 'dynamixel', version: 'base', audience: 'external' } }
export function readProgress(): Progress {
  let progress: Progress
  try {
    progress = validateProgress(JSON.parse(localStorage.getItem(PROGRESS_KEY) ?? 'null'))
  } catch { progress = structuredClone(EMPTY_PROGRESS) }
  return Object.keys(LINK_BUILD).length ? changeBuildProgress(progress, LINK_BUILD) : progress
}
// A link can name the build: the QR on a kit's label sheet opens the guide set to that
// kit, ?side=l|r&motor=dx|ft (left/right, dynamixel/feetech also read). Read once when
// the page loads; useAssemblyProgress then takes it off the address, so a later change
// in the Hand or Motors picker survives a reload.
export function buildFromLink(search: string): Partial<Build> {
  const q = new URLSearchParams(search), out: Partial<Build> = {}
  const side = (q.get('side') ?? '').toLowerCase(), motor = (q.get('motor') ?? '').toLowerCase()
  if (side === 'l' || side === 'left') out.side = 'left'
  else if (side === 'r' || side === 'right') out.side = 'right'
  if (motor === 'dx' || motor === 'dynamixel') out.motor = 'dynamixel'
  else if (motor === 'ft' || motor === 'feetech') out.motor = 'feetech'
  return out
}
export const LINK_BUILD: Partial<Build> = WEB_GUIDE && typeof window !== 'undefined' ? buildFromLink(window.location.search) : {}
export function dropLinkBuild() {
  const url = new URL(window.location.href)
  if (!url.searchParams.has('side') && !url.searchParams.has('motor')) return
  url.searchParams.delete('side'); url.searchParams.delete('motor')
  window.history.replaceState(window.history.state, '', url)
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
    if(parsed?.views?.['guide:layout']!=='oct16-v1')progress.done=progress.done.filter(id=>!['prepare-pp','p33'].includes(id))
    progress.views['guide:layout']='oct16-v1'
    if (!progress.checks.includes('p1:0') || !progress.checks.includes('p1:1')) progress.done = progress.done.filter(id => id !== 'p1')
    if(parsed?.views?.['guide:finger-layout']!=='parts-first-v1')progress.done=progress.done.filter(id=>!['p31','p33','p35','finishing-pp'].includes(id))
    progress.views['guide:finger-layout']='parts-first-v1'
    if(parsed?.views?.['guide:thumb-layout']!=='parts-first-v1')progress.done=progress.done.filter(id=>!['p46','p59','p62'].includes(id))
    progress.views['guide:thumb-layout']='parts-first-v1'
    if(parsed?.views?.['guide:thumb-cables']!=='oct18-v1'){
      const changed=['thumb-tendons','thumb-pp','p26','p75',...(progress.build.version==='touch'?['pp-ready','thumb-pp-ready','touch-route','touch-connect','touch-mount','touch-skins']:[])]
      if(!parsed?.done?.includes('p52'))changed.push('p49')
      progress.done=progress.done.filter(id=>!changed.includes(id))
      progress.checks=progress.checks.filter(key=>!changed.some(id=>key.startsWith(`${id}:`)))
    }
    progress.views['guide:thumb-cables']='oct18-v1'
    if(progress.build.version==='base')progress.current=BASE_STEP_REDIRECTS[progress.current]??progress.current
    if(progress.build.version==='touch'){
      if(['finishing-pp','thumb-skins'].includes(progress.current))progress.current='touch-skins'
      progress.done=progress.done.filter(id=>!['finishing-pp','thumb-skins'].includes(id))
    }
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
      current: ['p105','p110','p150','p154'].includes(data.current)?'p101':data.current==='p52'?'p49':data.current==='p40'?'p37':data.current==='p97'?'p99':['p117','p119'].includes(data.current) ? 'p115' : STEPS.some(s => s.id === data.current) ? data.current : EMPTY_PROGRESS.current,
      done: Array.isArray(data.done) ? [...new Set<string>(data.done.filter((id: unknown) => STEPS.some(s => s.id === id)))] : [],
      tendons: Array.isArray(data.tendons) ? [...new Set<number>(data.tendons.filter((n: unknown) => typeof n === 'number' && Number.isInteger(n) && n >= 0 && n < 32))] : [],
      checks: Array.isArray(data.checks) ? [...new Set<string>(data.checks.filter((s: unknown) => typeof s === 'string'))] : [],
      views: data.views && typeof data.views === 'object' && !Array.isArray(data.views) ? Object.fromEntries(Object.entries(data.views).filter(([, value]) => typeof value === 'string')) as Record<string,string> : {},
      build: { audience: WEB_GUIDE || data.build?.audience === 'external' ? 'external' : 'internal', side: data.build?.side === 'left' ? 'left' : 'right', motor: data.build?.motor === 'feetech' ? 'feetech' : 'dynamixel', version: WEB_GUIDE ? 'base' : data.build?.version === 'full' || data.build?.sensing === 'joint' ? 'full' : data.build?.version === 'touch' || data.build?.sensing === 'touch' ? 'touch' : 'base' },
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
  return {...progress,current:(value.version??progress.build.version)==='base'?(BASE_STEP_REDIRECTS[progress.current]??progress.current):progress.current,build:{...progress.build,...value},done:progress.done.filter(id=>!affected.includes(id)),
    checks:progress.checks.filter(key=>!affected.some(id=>key.startsWith(`${id}:`))),
    tendons:side||version?[]:progress.tendons,
    views:side||version?{'guide:revision':'assembly-v5','guide:feedback':'oct15-v1','guide:layout':'oct16-v1','guide:finger-layout':'parts-first-v1','guide:thumb-layout':'parts-first-v1','guide:thumb-cables':'oct18-v1','flashing:method':flashingMethod(progress)}:progress.views}
}

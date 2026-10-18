import {Fragment,useEffect,useId,useState,useRef,useLayoutEffect,type ReactNode} from 'react'
import navigationHand from './navigationHand.json'
import type {AssemblyStep} from './guide'
import type {Build} from './buildContent'

const CHAPTER_NAMES:Record<string,string> = {
  'Start here':'Your ORCA hand','Fundamentals':'Glossary','Prepare the parts':'Prepare the parts',
  'Fingers':'Assemble the index finger','Other fingers':'Assemble the other fingers',
  'Thumb':'Assemble the thumb','Carpals':'Assemble the palm','Wrist & routing':'Route and fit the wrist',
  'Tower':'Build the tower','Electronics':'Prepare the control board',
  'Flashing · ORCA Console':'Flash the boards','Flashing · orca_firmware':'Flash the boards',
  'Motors':'Install the motors','Spooling':'Wind the tendons','Hull':'Fit the covers',
  'Touch skins':'Fit the finger skins','Touch sensors':'Install Touch sensors','Touch connector board':'Connect the Touch board',
  'Finish':'Check and commission','Appendix · arm mounting':'Mount to a robot arm','Appendix · silicone':'Make silicone skins',
}
export const chapterKey=(step:AssemblyStep)=>step.id==='p45'?'Other fingers':step.chapter
export const chapterTitle=(step:AssemblyStep)=>CHAPTER_NAMES[chapterKey(step)]??step.chapter
const regionFor=(step:AssemblyStep)=>({Fingers:'index','Other fingers':'fingers',Thumb:'thumb',Carpals:'palm','Wrist & routing':'wrist',Tower:'tower',Motors:'tower',Spooling:'tower',Hull:'tower'}[chapterKey(step)]??'')
const REGIONS=[
  {id:'thumb',label:'Thumb',step:'thumb-tendons'},
  {id:'index',label:'Index finger',step:'p26'},
  {id:'middle',label:'Middle finger',step:'p45'},
  {id:'ring',label:'Ring finger',step:'p45'},
  {id:'pinky',label:'Pinky finger',step:'p45'},
  {id:'palm',label:'Palm / carpals',step:'p64'},
  {id:'wrist',label:'Wrist',step:'p75'},
  {id:'tower',label:'Tower and motors',step:'p93'},
]

export function AssemblyNavigation({steps,current,done,query,filtered,build,onGo,beforeContents,title}:{title:(step:AssemblyStep)=>string;beforeContents?:ReactNode;steps:AssemblyStep[];current:AssemblyStep;done:string[];query:string;filtered:AssemblyStep[];build:Build;onGo:(id:string)=>void}) {
  const maskId=useId(),contents=useRef<HTMLElement>(null)
  const [jump,setJump]=useState(0)
  const active=chapterKey(current),[open,setOpen]=useState(active),[picked,setPicked]=useState('')
  useLayoutEffect(()=>{
    const nav=contents.current;if(!nav)return
    const reveal=()=>{
      const target=nav.querySelector<HTMLElement>('[aria-current=step]');if(!target||!nav.clientHeight)return
      const box=nav.getBoundingClientRect(),row=target.getBoundingClientRect()
      const chapter=target.closest('.assembly-chapter')?.querySelector('.assembly-chapter-button')?.getBoundingClientRect()
      const top=chapter&&row.bottom-chapter.top<nav.clientHeight*.7?chapter.top:row.top
      if(top<box.top+12||row.bottom>box.bottom-12)nav.scrollTo({top:nav.scrollTop+top-box.top-12,behavior:'instant'})
    }
    const frame=requestAnimationFrame(reveal),observer=new ResizeObserver(reveal);observer.observe(nav)
    return()=>{cancelAnimationFrame(frame);observer.disconnect()}
  },[current.id,jump,query,open])
  useEffect(()=>{setOpen(active)},[active])
  const chapters=[...new Set(steps.map(chapterKey))]
  const region=regionFor(current)
  const pickedActive=REGIONS.find(r=>r.id===picked)?.step===current.id?picked:''
  const select=(id:string,step:string)=>{const target=steps.find(s=>s.id===step);if(target)setOpen(chapterKey(target));onGo(step);setPicked(id);setJump(n=>n+1)}
  let previousPhase=''
  return <div className="assembly-navigation-layers">
    <div className="assembly-hand-navigation">
      <div className="assembly-row"><span className="assembly-eyebrow">Jump to a part</span><span>{build.side==='left'?'Left':'Right'} hand</span></div>
      <svg viewBox="0 0 640 900" aria-label="Choose a hand part to open its assembly chapter">
        <defs><mask id={maskId} style={{maskType:'alpha'}}><image href={`./assembly/navigation/${build.version==='touch'?'touch':'base'}-right.webp`} width="640" height="900"/></mask></defs>
        <g transform={build.side==='left'?'translate(640 0) scale(-1 1)':undefined}>
          <image href={`./assembly/navigation/${build.version==='touch'?'touch':'base'}-right.webp`} width="640" height="900"/>
          {[...REGIONS].reverse().map(r=>{
            const boxes=navigationHand[build.version==='touch'?'touch':'base'].regions[r.id as keyof typeof navigationHand.base.regions]
            const x=Math.min(...boxes.map(b=>b[0])),y=Math.min(...boxes.map(b=>b[1])),right=Math.max(...boxes.map(b=>b[0]+b[2])),bottom=Math.max(...boxes.map(b=>b[1]+b[3]))
            const selected=pickedActive?pickedActive===r.id:region===r.id||region==='fingers'&&['middle','ring','pinky'].includes(r.id)
            return <g key={r.id} role="button" tabIndex={0} aria-label={`Open ${r.label} assembly`} aria-pressed={selected} className={selected?'selected':''} onClick={()=>select(r.id,r.step)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(r.id,r.step)}}}>
              <title>{r.label}</title><rect x={x} y={y} width={right-x} height={bottom-y} rx={8} mask={`url(#${maskId})`}/>
            </g>
          })}
        </g>
      </svg>
      <p aria-live="polite">{pickedActive?REGIONS.find(r=>r.id===pickedActive)?.label:region==='fingers'?'Middle · ring · pinky':REGIONS.find(r=>r.id===region)?.label??'Select a finger, palm, wrist or tower'}</p>
    </div>
    <nav ref={contents} className="assembly-contents-scroll" aria-label="Assembly chapters">
      {beforeContents}
      {chapters.map((chapter,n)=>{
        const all=steps.filter(s=>chapterKey(s)===chapter),matches=filtered.filter(s=>chapterKey(s)===chapter)
        if(!matches.length)return null
        const expanded=Boolean(query.trim())||open===chapter
        const required=all.filter(s=>!s.hint)
        const count=required.filter(s=>done.includes(s.id)).length
        const phase=chapter.startsWith('Appendix')?'Optional':n<3?'Prepare':['Fingers','Other fingers','Thumb','Touch sensors','Touch skins'].includes(chapter)?'Build the fingers':['Carpals','Wrist & routing','Tower'].includes(chapter)?'Build the hand':'Complete the hand'
        const showPhase=phase!==previousPhase;previousPhase=phase
        return <div className="assembly-chapter" key={chapter}>
          {showPhase&&<p className="assembly-nav-phase">{phase}</p>}
          <button className={`assembly-chapter-button ${chapter===active?'active':''}`} aria-expanded={expanded} aria-controls={`chapter-${n}`} onClick={()=>setOpen(expanded?'':chapter)}>
            <span className={count===required.length?'is-complete':''}>{count===required.length?'✓':String(n+1).padStart(2,'0')}</span><span>{CHAPTER_NAMES[chapter]??chapter}</span><small>{count}/{required.length} <span aria-hidden="true">{expanded?'−':'+'}</span></small>
          </button>
          {expanded&&<div className="assembly-step-links" id={`chapter-${n}`}>{matches.map((s,i)=><Fragment key={s.id}>{s.section&&s.section!==matches[i-1]?.section&&<h4 className="assembly-step-section">{s.section}</h4>}<button className={`${s.id===current.id?'active':''} ${s.hint?'assembly-hint-link':''}`} aria-current={s.id===current.id?'step':undefined} onClick={()=>{setPicked('');onGo(s.id)}}><span aria-label={s.hint?'Optional hint':done.includes(s.id)?'Completed':'Incomplete'}>{s.hint?'HINT':done.includes(s.id)?'✓':String((s.section?required.filter(item=>item.section===s.section):required).indexOf(s)+1).padStart(2,'0')}</span><span>{title(s)}</span></button></Fragment>)}</div>}
        </div>
      })}
      {!filtered.length&&<p className="assembly-muted">No matching steps. Try “wrist” or “PTFE”.</p>}
    </nav>
  </div>
}

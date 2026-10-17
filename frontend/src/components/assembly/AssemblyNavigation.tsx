import {useEffect,useState} from 'react'
import type {AssemblyStep} from './guide'
import type {Build} from './buildContent'

const CHAPTER_NAMES:Record<string,string> = {
  'Start here':'Your build','Fundamentals':'Know the hand','Prepare the parts':'Prepare the parts',
  'Fingers':'Assemble the index finger','Other fingers':'Assemble the other fingers',
  'Thumb':'Assemble the thumb','Carpals':'Assemble the palm','Wrist & routing':'Route and fit the wrist',
  'Tower':'Build the tower','Electronics':'Prepare the control board',
  'Flashing · ORCA Console':'Flash the boards','Flashing · orca_firmware':'Flash the boards',
  'Motors':'Install the motors','Spooling':'Wind the tendons','Hull':'Fit the covers',
  'Touch sensors':'Install Touch sensors','Touch connector board':'Connect the Touch board',
  'Finish':'Check and commission','Appendix · arm mounting':'Mount to a robot arm','Appendix · silicone':'Make silicone skins',
}
export const chapterKey=(step:AssemblyStep)=>step.id==='p45'?'Other fingers':step.chapter
export const chapterTitle=(step:AssemblyStep)=>CHAPTER_NAMES[chapterKey(step)]??step.chapter
const regionFor=(step:AssemblyStep)=>({Fingers:'index','Other fingers':'fingers',Thumb:'thumb',Carpals:'palm','Wrist & routing':'wrist',Tower:'tower',Motors:'tower',Spooling:'tower',Hull:'tower'}[chapterKey(step)]??'')
const REGIONS=[
  {id:'thumb',label:'Thumb',step:'p46',d:'M54 116 L34 91 Q26 82 20 89 Q14 95 20 105 L44 142 Q49 148 56 139Z'},
  {id:'index',label:'Index finger',step:'p26',d:'M61 100 L57 42 Q57 30 66 30 Q75 30 76 42 L80 101Z'},
  {id:'middle',label:'Middle finger',step:'p45',d:'M87 98 L85 22 Q85 10 95 10 Q105 10 105 22 L106 98Z'},
  {id:'ring',label:'Ring finger',step:'p45',d:'M114 100 L115 33 Q115 22 125 23 Q134 24 134 35 L133 103Z'},
  {id:'pinky',label:'Pinky finger',step:'p45',d:'M140 106 L144 60 Q145 50 153 51 Q162 52 161 62 L157 115Z'},
  {id:'palm',label:'Palm / carpals',step:'p64',d:'M62 106 Q105 99 153 118 L147 151 Q145 161 135 164 L76 164 Q64 162 60 150 L51 137Z'},
  {id:'wrist',label:'Wrist',step:'p75',d:'M76 170 L136 170 L139 187 L73 187Z'},
  {id:'tower',label:'Tower and motors',step:'p93',d:'M78 194 L134 194 L140 218 L72 218Z'},
]

export function AssemblyNavigation({steps,current,done,query,filtered,build,onGo}:{steps:AssemblyStep[];current:AssemblyStep;done:string[];query:string;filtered:AssemblyStep[];build:Build;onGo:(id:string)=>void}) {
  const active=chapterKey(current),[open,setOpen]=useState(active),[picked,setPicked]=useState('')
  useEffect(()=>{setOpen(active)},[active])
  const chapters=[...new Set(steps.map(chapterKey))]
  const region=regionFor(current)
  const pickedActive=REGIONS.find(r=>r.id===picked)?.step===current.id?picked:''
  const select=(id:string,step:string)=>{const target=steps.find(s=>s.id===step);if(target)setOpen(chapterKey(target));onGo(step);setPicked(id)}
  let previousPhase=''
  return <>
    <div className="assembly-hand-navigation">
      <div className="assembly-row"><span className="assembly-eyebrow">Jump to a part</span><span>{build.side==='left'?'Left':'Right'} hand</span></div>
      <svg viewBox="0 0 200 230" aria-label="Choose a hand part to open its assembly chapter">
        <g transform={build.side==='left'?'translate(200 0) scale(-1 1)':undefined}>
          {REGIONS.map(r=>{
            const selected=pickedActive?pickedActive===r.id:region===r.id||region==='fingers'&&['middle','ring','pinky'].includes(r.id)
            return <g key={r.id} role="button" tabIndex={0} aria-label={`Open ${r.label} assembly`} aria-pressed={selected} className={selected?'selected':''} onClick={()=>select(r.id,r.step)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(r.id,r.step)}}}>
              <title>{r.label}</title><path d={r.d}/>
            </g>
          })}
          <path className="assembly-hand-joints" d="M60 60L77 59 M62 81L79 80 M86 43L105 43 M87 69L106 69 M115 54L134 55 M114 78L133 79 M142 79L159 81 M140 96L157 98 M28 111L40 101 M77 147Q105 151 135 146 M93 198L93 213 M119 198L119 213"/>
        </g>
      </svg>
      <p aria-live="polite">{pickedActive?REGIONS.find(r=>r.id===pickedActive)?.label:region==='fingers'?'Middle · ring · pinky':REGIONS.find(r=>r.id===region)?.label??'Select a finger, palm, wrist or tower'}</p>
    </div>
    <nav aria-label="Assembly chapters">
      {chapters.map((chapter,n)=>{
        const all=steps.filter(s=>chapterKey(s)===chapter),matches=filtered.filter(s=>chapterKey(s)===chapter)
        if(!matches.length)return null
        const expanded=Boolean(query.trim())||open===chapter
        const count=all.filter(s=>done.includes(s.id)).length
        const phase=chapter.startsWith('Appendix')?'Optional':n<3?'Prepare':['Fingers','Other fingers','Thumb','Carpals','Wrist & routing'].includes(chapter)?'Build the hand':'Complete the hand'
        const showPhase=phase!==previousPhase;previousPhase=phase
        return <div className="assembly-chapter" key={chapter}>
          {showPhase&&<p className="assembly-nav-phase">{phase}</p>}
          <button className={`assembly-chapter-button ${chapter===active?'active':''}`} aria-expanded={expanded} aria-controls={`chapter-${n}`} onClick={()=>setOpen(expanded?'':chapter)}>
            <span className={count===all.length?'is-complete':''}>{count===all.length?'✓':String(n+1).padStart(2,'0')}</span><span>{CHAPTER_NAMES[chapter]??chapter}</span><small>{count}/{all.length} <span aria-hidden="true">{expanded?'−':'+'}</span></small>
          </button>
          {expanded&&<div className="assembly-step-links" id={`chapter-${n}`}>{matches.map((s)=><button key={s.id} className={s.id===current.id?'active':''} aria-current={s.id===current.id?'step':undefined} onClick={()=>{setPicked('');onGo(s.id)}}><span aria-label={done.includes(s.id)?'Completed':'Incomplete'}>{done.includes(s.id)?'✓':String(all.indexOf(s)+1).padStart(2,'0')}</span><span>{s.title}</span></button>)}</div>}
        </div>
      })}
      {!filtered.length&&<p className="assembly-muted">No matching steps. Try “wrist” or “PTFE”.</p>}
    </nav>
  </>
}

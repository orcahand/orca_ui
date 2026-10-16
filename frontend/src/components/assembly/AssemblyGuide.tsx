import {RoutingInspection} from './RoutingInspection'
import { memo, useRef, useState, type ReactNode } from 'react'
import { type AssemblyStep } from './guide'
import { lazy, Suspense } from 'react'
import { TendonPreparation, KnotReinforcement } from './TendonPreparation'
import { FingerMotion } from './FingerMotion'
import { FINGER_CHECKS } from './fingerMovements'
import { DriveExplorer } from './DriveExplorer'
import { CadDetail } from './CadDetail'
import { CAD_DETAILS } from './cadDetails'
import { MotorCheck } from './MotorCheck'
import { MotorChain } from './MotorChain'
import { JointInspection } from './JointInspection'
import { ReviewChanges, SHOW_ASSEMBLY_REVIEW_NOTES } from './ReviewChanges'
import { WristRouting } from './WristRouting'
import { ASSEMBLY_MOTIONS } from './assemblyMotions'
import { TendonRouting } from './TendonRouting'
import { HandLabels } from './HandLabels'
import { KnotLesson } from './KnotLesson'
import localClips from './local-clips.json'
import { ThreadingAnimation } from './ThreadingAnimation'
import { EMPTY_PROGRESS, changeBuildProgress, flashingMethod } from './progress'
import { useAssemblyProgress } from './useAssemblyProgress'
import { buildSteps, commands, FINAL_CHECKS, figures, GLOSSARY, instructions, kit, note, type Build, type Figure } from './buildContent'
import './assembly.css'
import './review.css'

const MOTION_AT:Record<string,number>={p33:0,p42:1,p46:0,p54:0,p62:0,p64:1,p68:1,p89:1,p99:1,p122:1,p123:1,p126:2}
const INSPECTION_AT:Record<string,number>={p33:1,p42:2,p46:2,p54:2,p62:2,p64:2,p68:2,p89:1}
const DETAIL_AT:Record<string,number>={'finishing-pp':0,p73:1,p98:0,p127:1,p129:1,p139:1}
const PartsExplorer = lazy(() => import('./PartsExplorer').then(m=>({default:m.PartsExplorer})))
export function AssemblyGuide({ onClose, safetyControl }: { onClose: () => void; safetyControl?: ReactNode }) {
  const {progress,setProgress,ready,saveStatus} = useAssemblyProgress()
  const [query, setQuery] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [sidebarCollapsed,setSidebarCollapsed] = useState(false)
  const [reviewNotes,setReviewNotes] = useState(true)
  const [resetting, setResetting] = useState(false)
  const [glossary, setGlossary] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const main = useRef<HTMLElement>(null)
  const method=flashingMethod(progress)
  const STEPS = buildSteps(progress.build,method)
  const CHAPTERS=[...new Set(STEPS.map(s=>s.chapter))]
  const step = STEPS.find(s => s.id === progress.current) ?? STEPS[0]
  const index = STEPS.indexOf(step)
  const completed = STEPS.filter(s=>progress.done.includes(s.id)).length
  const done = progress.done.includes(step.id)
  const build = progress.build
  const copy = instructions(step, build)
  const stepFigures = figures(step, build)
  const warning = note(step, build)
  const checklist = step.id === 'p139' ? FINAL_CHECKS : step.id === 'p45' ? FINGER_CHECKS : []
  const checkKey=(i:number)=>step.id==='p45'?`p45:finger:${i}`:`${step.id}:${i}`
  const allChecked = step.id === 'motor-check' ? Array.from({length:17},(_,i)=>`motor-check:${i+1}`).every(k=>progress.checks.includes(k)) : step.id === 'p83' ? progress.tendons.length === 32 : ['p123','p126'].includes(step.id) ? progress.checks.filter(k=>k.startsWith(`${step.id}:tendon:`)).length===32 : checklist.every((_,i) => progress.checks.includes(checkKey(i)))
  const percent = Math.round(completed / STEPS.length * 100)
  function go(id: string) {
    setProgress(p => ({ ...p, current: id }))
    setNavOpen(false)
    main.current?.scrollTo({ top: 0, behavior: 'instant' })
    requestAnimationFrame(() => heading.current?.focus({ preventScroll: true }))
  }
  function changeBuild(value: Partial<Build>) { setProgress(p=>changeBuildProgress(p,value)) }
  function chooseFlashing(next: 'console'|'firmware') {
    setProgress(p=>({...p,views:{...p.views,'flashing:method':next},current:step.chapter.startsWith('Flashing')?(next==='console'?(['p110','p154'].includes(step.id)?'p110':'p105'):(['p110','p154'].includes(step.id)?'p154':'p150')):p.current}))
  }
  function toggleDone() {
    if (!done && !allChecked) return
    setProgress(p => ({ ...p, done: done ? p.done.filter(id => id !== step.id) : [...p.done, step.id] }))
  }
  function toggleCheck(key: string) {
    setProgress(p => {
      const checks=p.checks.includes(key)?p.checks.filter(k=>k!==key):[...p.checks,key]
      const remaining=p.done.filter(id=>id!==step.id)
      return {...p,checks,done:step.id==='p45'&&FINGER_CHECKS.every((_,i)=>checks.includes(`p45:finger:${i}`))?[...remaining,step.id]:remaining}
    })
  }
  const filtered = STEPS.filter(s => `${s.title} ${s.chapter} ${instructions(s,build).join(' ')} ${kit(s,build).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase()))
  if (!ready) return <div className="assembly-loading"><p>Restoring your build…</p><button className="btn" onClick={onClose}>Close</button></div>
  return <div className="assembly-app">
    <header className="assembly-header">
      <div className="assembly-brand">◈ ORCA <span>ASSEMBLY WORKSPACE</span></div>
      <div className="assembly-header-actions">
        {safetyControl}

        {SHOW_ASSEMBLY_REVIEW_NOTES&&<button className="assembly-text-button" aria-pressed={reviewNotes} onClick={()=>setReviewNotes(!reviewNotes)}>{reviewNotes?'Hide change notes':'Show change notes'}</button>}
        <button className="assembly-text-button" aria-expanded={glossary} onClick={() => setGlossary(!glossary)}>Parts & terms</button>
        <button className="assembly-close" onClick={onClose} aria-label="Save and close assembly guide">Save & close ×</button>
      </div>
    </header>
    {glossary && <section className="assembly-glossary" aria-label="Parts and terms"><div className="assembly-row"><h2>Know your parts</h2><button className="assembly-text-button" onClick={() => setGlossary(false)}>Close glossary ×</button></div><dl>{GLOSSARY.map(([term,definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section>}
    <div className={`assembly-layout ${sidebarCollapsed?'is-sidebar-collapsed':''}`}>
      <button className="assembly-mobile-nav" onClick={() => setNavOpen(!navOpen)} aria-expanded={navOpen} aria-controls="assembly-navigation">{navOpen ? 'Close chapters' : `Chapters · ${step.chapter}`} ☰</button>
      <aside className={`assembly-sidebar ${navOpen ? 'is-open' : ''}`} id="assembly-navigation">
        <div className="assembly-sidebar-intro"><span className="assembly-eyebrow">THE BUILD GUIDE</span><h1>Every part.<br />One hand.</h1><p>ORCA hand · V2.1</p></div>
        <div className="assembly-progress"><div className="assembly-row"><span>{completed} / {STEPS.length} steps</span><strong>{percent}%</strong></div><progress value={completed} max={STEPS.length} aria-label="Assembly progress" /></div>
        <label className="assembly-search"><span className="assembly-sr-only">Search assembly instructions</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a part or step…" /></label>
        <nav aria-label="Assembly chapters">
          {CHAPTERS.map((chapter,n) => {
            const chapterSteps = filtered.filter(s => s.chapter === chapter)
            if (!chapterSteps.length) return null
            const expanded = Boolean(query) || chapter === step.chapter
            const count = STEPS.filter(s => s.chapter === chapter && progress.done.includes(s.id)).length
            return <div className="assembly-chapter" key={chapter}>
              <button className={`assembly-chapter-button ${expanded ? 'active' : ''}`} onClick={() => go(chapterSteps[0].id)}><span>{String(n+1).padStart(2,'0')}</span><span>{chapter}</span><small>{count}/{STEPS.filter(s => s.chapter === chapter).length}</small></button>
              {expanded && <div className="assembly-step-links">{chapterSteps.map(s => <button key={s.id} className={s.id === step.id ? 'active' : ''} aria-current={s.id === step.id ? 'step' : undefined} onClick={() => go(s.id)}><span aria-label={progress.done.includes(s.id) ? 'Completed' : 'Incomplete'}>{progress.done.includes(s.id) ? '✓' : '·'}</span>{s.title}</button>)}</div>}
            </div>
          })}
          {!filtered.length && <p className="assembly-muted">No matching steps. Try “wrist” or “PTFE”.</p>}
        </nav>
        <div className="assembly-save-status" role="status">{saveStatus}</div>
        {resetting ? <div className="assembly-reset"><p>Clear assembly progress for a new build?</p><button onClick={() => { setProgress(EMPTY_PROGRESS); setResetting(false); main.current?.scrollTo(0,0) }}>Clear progress</button><button onClick={() => setResetting(false)}>Cancel</button></div> : <button className="assembly-text-button" onClick={() => setResetting(true)}>Start a new build</button>}
      </aside>
      <main ref={main} className="assembly-main">
        <button className="assembly-sidebar-chevron" aria-label={sidebarCollapsed?'Expand chapters':'Collapse chapters'} title={sidebarCollapsed?'Expand chapters':'Collapse chapters'} aria-expanded={!sidebarCollapsed} aria-controls="assembly-navigation" onClick={()=>setSidebarCollapsed(!sidebarCollapsed)}>{sidebarCollapsed?'›':'‹'}</button>
        <div className="assembly-breadcrumb"><span>{step.chapter}</span><span>STEP {String(index+1).padStart(2,'0')} / {STEPS.length}</span></div>
        <h2 ref={heading} tabIndex={-1}>{step.title}</h2>
        {step.id!=='p1'&&build.version==='full'&&(ASSEMBLY_MOTIONS[step.id]||['p23','p35','p45','p80','p83','p115','p123','p126'].includes(step.id))&&<p className="assembly-muted">Mechanical reference: Base geometry. Full-specific sensor parts are not represented in this model.</p>}
        {step.id==='p23'&&build.motor==='feetech'&&<p className="assembly-muted">The anatomy reference uses a Dynamixel wrist and tower; use the FeeTech parts for your build.</p>}
        {step.id === 'p1' && <div className="assembly-step-meta assembly-config-chips">
          <label><span className="assembly-sr-only">Hand</span><select aria-label="Hand" value={build.side} onChange={e=>changeBuild({side:e.target.value as Build['side']})}><option value="right">Right hand</option><option value="left">Left hand</option></select></label>
          <label><span className="assembly-sr-only">Motors</span><select aria-label="Motors" value={build.motor} onChange={e=>changeBuild({motor:e.target.value as Build['motor']})}><option value="dynamixel">Dynamixel</option><option value="feetech">FeeTech</option></select></label>
          <label><span className="assembly-sr-only">Version</span><select aria-label="Version" value={build.version} onChange={e=>changeBuild({version:e.target.value as Build['version']})}><option value="base">Base</option><option value="touch">Touch</option><option value="full">Full</option></select></label>
          <label><span className="assembly-sr-only">Guide edition</span><select aria-label="Guide edition" value={build.audience} onChange={e=>changeBuild({audience:e.target.value as Build['audience']})}><option value="internal">Internal</option><option value="external">External</option></select></label>
          </div>}
        {build.audience==='internal'&&step.chapter.startsWith('Flashing')&&<section className="assembly-flashing-choice"><h3>Choose one flashing method</h3><p>Both methods prepare the same boards. Complete the selected method; you do not need to flash them twice.</p><div className="assembly-clip-tabs"><button aria-pressed={method==='console'} onClick={()=>chooseFlashing('console')}>ORCA Console</button><button aria-pressed={method==='firmware'} onClick={()=>chooseFlashing('firmware')}>orca_firmware · terminal</button></div></section>}
        {step.id !== 'p1' && kit(step,build).length>0 && <div className="assembly-kit"><span className="assembly-eyebrow">Parts</span><ul>{kit(step,build).map(item => <li key={item}>{item}</li>)}</ul></div>}
        {step.id === 'p1' && <><Suspense fallback={<p>Loading your hand…</p>}><PartsExplorer build={build}/></Suspense>{build.version==='touch'&&<p className="assembly-muted">Includes Touch sensor preparation, cable wrapping, installation and connector-board flashing before closing the palm.</p>}{build.version==='full'&&<p className="assembly-note">Full-specific sensor installation and harness routing still need a verified procedure before closing the hand.</p>}</>}
        {step.id === 'p6' && <><KnotLesson/><StepVideos key="knot-video" step={step} build={build}/></>}
        {step.id === 'p23' && <HandLabels build={build}/>}
        {step.id.startsWith('touch-')&&['touch-ids','touch-test'].includes(step.id)&&<table className="assembly-sensor-ids"><caption>Sensor IDs</caption><thead><tr><th scope="col">Finger</th><th scope="col">ID</th></tr></thead><tbody>{['Thumb','Index','Middle','Ring','Pinky'].map((finger,id)=><tr key={finger}><th scope="row">{finger}</th><td>{id}</td></tr>)}</tbody></table>}
        {!['p1','p6','p23'].includes(step.id) && <div className="assembly-guided-content">
          {warning && <div className="assembly-note"><p>{warning}</p></div>}

          <ol className="assembly-guided-instructions">{copy.map((instruction,i) => {
            const images=stepFigures.filter(f=>(f.instruction??1)===i+1)
            const command=commands(step,build).filter((_,n)=>i===(step.id==='p150'?(n===0?0:2):step.id==='p154'?1:0))
            return <li key={`${step.id}:${i}`} value={i+1}>
              <p className="assembly-guided-text"><span aria-hidden="true">{i+1}</span>{instruction}</p>
              {command.map(text=><Command key={text} command={text}/>)}
              {['p105','p110'].includes(step.id)&&i===0&&<a className="assembly-inline-resource" href="https://orca-console-169809101000.europe-west6.run.app" target="_blank" rel="noreferrer">Open ORCA Console flashing tool ↗</a>}
              {images.length>0&&<MediaGallery key={`${step.id}-${build.side}-${build.motor}-${build.version}-${i}`} items={images} focused={-1} saved={progress.views[step.id]} onSelect={src=>setProgress(p=>({...p,views:{...p.views,[step.id]:src}}))}/>}
              {step.id==='p139'&&i===0&&checklist.length > 0 && <section className="assembly-work-checklist"><h3>{step.id === 'p139' ? 'Final assembly checklist' : 'Finger movement checklist'}</h3>{checklist.map((label,i) => <label key={label}><input type="checkbox" checked={progress.checks.includes(checkKey(i))} onChange={() => toggleCheck(checkKey(i))} /><span>{label}</span></label>)}</section>}
        {i===1&&step.id==='motor-check'&&<MotorCheck build={build} selected={Number(progress.views['motor-check:selected']??1)} onSelect={id=>setProgress(p=>({...p,views:{...p.views,'motor-check:selected':String(id)}}))} checked={Array.from({length:17},(_,i)=>i+1).filter(id=>progress.checks.includes(`motor-check:${id}`))} onCheck={id=>toggleCheck(`motor-check:${id}`)}/>}
        {i===(DETAIL_AT[step.id]??copy.length-1)&&CAD_DETAILS[step.id]&&step.id!=='p46'&&!(build.motor==='feetech'&&CAD_DETAILS[step.id].motorSpecific)&&<CadDetail key={step.id} build={build} step={step.id}/>}
        {i===0&&step.id==='p115'&&<MotorChain build={build}/>}
        {i===1&&['p37','p49','p56'].includes(step.id)&&<KnotReinforcement count={step.id==='p37'?1:3}/>}
        {i===1&&step.id === 'p26' && <TendonPreparation/>}
        {i===1&&step.id === 'p59' && <TendonRouting step={step.id} build={build}/>}
        {i===1&&step.id === 'p77' && <WristRouting build={build}/>}
        {i===0&&step.id === 'p80' && <RoutingInspection build={build}/>}
        {i===(step.id==='p35'?1:2)&&['p35','p45'].includes(step.id) && <FingerMotion build={build} indexOnly={step.id==='p35'}/>}

        {i===(MOTION_AT[step.id]??copy.length-1)&&ASSEMBLY_MOTIONS[step.id] && step.id!=='p93' && !(build.motor==='feetech'&&ASSEMBLY_MOTIONS[step.id].motorSpecific) && <ThreadingAnimation key={`motion:${step.id}`} kind={step.animation??'straight'} build={build} step={step.id} />}
        {i===INSPECTION_AT[step.id]&&<JointInspection build={build} step={step.id}/>}
        {i===2&&step.id==='p46'&&<CadDetail build={build} step={step.id}/>}
        {i===(step.id==='p83'?1:3)&&['p83','p123','p126'].includes(step.id)&&<DriveExplorer key={`drive:${step.id}`} build={build} stage={step.id==='p83'?'wrist':step.id==='p123'?'bottom':'top'} checked={step.id==='p83'?progress.tendons:progress.checks.filter(k=>k.startsWith(`${step.id}:tendon:`)).map(k=>Number(k.split(':').at(-1)))} onCheck={i=>setProgress(p=>step.id==='p83'?({...p,tendons:p.tendons.includes(i)?p.tendons.filter(n=>n!==i):[...p.tendons,i],done:p.done.filter(id=>id!==step.id)}):({...p,checks:p.checks.includes(`${step.id}:tendon:${i}`)?p.checks.filter(k=>k!==`${step.id}:tendon:${i}`):[...p.checks,`${step.id}:tendon:${i}`],done:p.done.filter(id=>id!==step.id)}))}/>}

            </li>
          })}</ol>

          {step.id === 'p141' && <button className="assembly-primary" onClick={onClose}>Return to Setup</button>}
        </div>}

        {step.id!=='p139'&&checklist.length > 0 && <section className="assembly-work-checklist"><h3>{step.id === 'p139' ? 'Final assembly checklist' : 'Finger movement checklist'}</h3>{checklist.map((label,i) => <label key={label}><input type="checkbox" checked={progress.checks.includes(checkKey(i))} onChange={() => toggleCheck(checkKey(i))} /><span>{label}</span></label>)}</section>}

        {step.id === 'p1' ? <section className="assembly-check assembly-intro-checks" aria-label="Build preparation"><h3>Checklist</h3>{['I have selected the correct configuration for this build.', 'I have confirmed that I have all the necessary parts.'].map((text,i)=><label key={text}><input type="checkbox" checked={progress.checks.includes(`p1:${i}`)} onChange={()=>setProgress(p=>{
          const key=`p1:${i}`;const checks=p.checks.includes(key)?p.checks.filter(k=>k!==key):[...p.checks,key]
          return {...p,checks,done:checks.includes('p1:0')&&checks.includes('p1:1')?[...new Set([...p.done,'p1'])]:p.done.filter(id=>id!=='p1')}
        })}/><span>{text}</span></label>)}</section> : step.id !== 'p45' && <section className="assembly-check"><h3>Checklist</h3><label><input type="checkbox" checked={done} disabled={!done && !allChecked} onChange={toggleDone} /><span><span>{step.check}</span>{!allChecked && <small>Finish the checks above to mark this step complete.</small>}</span></label></section>}
        {completed === STEPS.length && <div className="assembly-finished" role="status"><h3>Build checklist complete.</h3><p>Your assembly and joint checks are saved.</p></div>}
        {SHOW_ASSEMBLY_REVIEW_NOTES&&reviewNotes&&<ReviewChanges key={step.id} step={step} build={build}/>}
        <footer className="assembly-footer"><button className="assembly-secondary" disabled={index === 0} onClick={() => go(STEPS[index-1].id)}>← Previous</button><span>{index < STEPS.length-1 ? `Up next: ${STEPS[index+1].title}` : 'End of the guide'}</span><button className="assembly-primary" disabled={index === STEPS.length-1} onClick={() => go(STEPS[index+1].id)}>Next step →</button></footer>
        {build.motor === 'feetech' && ['p97','p98','p115'].includes(step.id) && <FeeTechVideos key={`ft-${step.id}`} />}
        {step.id!=='p6'&&!(build.motor === 'feetech' && ['p89','p98','p112','p115','p122'].includes(step.id)) && <StepVideos key={`video:${step.id}`} step={step} build={build} />}

      </main>
    </div>
  </div>
}

function MediaGallery({ items, saved, onSelect, focused }: { items: Figure[]; focused:number; saved?: string; onSelect: (src: string) => void }) {
  const [selected,setSelected]=useState(Math.max(0,items.findIndex(item=>item.src===saved)))
  const [photo,setPhoto]=useState(false)
  const dialog=useRef<HTMLDialogElement>(null)
  const item=items[selected],shown=photo&&item.photo?item.photo:item
  const frames=items.flatMap((item,i)=>item.photo?[{i,photo:false},{i,photo:true}]:[{i,photo:false}])
  const frame=frames.findIndex(f=>f.i===selected&&f.photo===photo)
  function cycle(direction:number){const next=frames[(frame+direction+frames.length)%frames.length];setSelected(next.i);setPhoto(next.photo);onSelect(items[next.i].src)}
  function enlarge(index:number){setSelected(index);setPhoto(false);onSelect(items[index].src);dialog.current?.showModal()}
  return <section className="assembly-panel-gallery" style={{'--panel-columns':items.length===1?1:Math.min(5,Math.max(2,Math.ceil(items.length/2))) } as React.CSSProperties} aria-label="Assembly photos and diagrams">
    {items.map((item,i)=><figure key={item.src} data-contrast={item.contrast??false} data-wide={item.wide||undefined} className={focused<0?'':(item.instruction??i+1)===focused+1?'is-focused':'is-unfocused'}>
      <div className="assembly-row"><span className="assembly-panel-number" aria-label={`Instruction ${item.instruction??i+1}`}>{item.instruction??i+1}</span><button className="assembly-text-button" onClick={()=>enlarge(i)} aria-label={`Enlarge image ${i+1}`}>⤢</button></div>
      <button className="assembly-image-button" data-image-kind={item.photo?'cad':'photo'} onClick={()=>enlarge(i)} aria-label={`Enlarge detail ${i+1}`}><img src={item.src} alt={item.caption} loading="lazy"/></button>{item.showCaption&&<figcaption className="assembly-panel-caption">{item.caption}</figcaption>}
    </figure>)}
    <dialog ref={dialog} className="assembly-lightbox assembly-comparison" data-contrast={photo?false:item.contrast??false} data-image-kind={photo||!item.photo?'photo':'cad'} aria-label="Enlarged assembly image" onKeyDown={e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();cycle(e.key==='ArrowRight'?1:-1)}}} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}>
      <div className="assembly-row"><span>Instruction {item.instruction??selected+1}</span>{item.photo&&<div className="assembly-clip-tabs" aria-label="Image view"><button aria-pressed={!photo} onClick={()=>setPhoto(false)}>Model view</button><button aria-pressed={photo} onClick={()=>setPhoto(true)}>Assembly photo</button></div>}<button autoFocus onClick={()=>dialog.current?.close()}>Close image ×</button></div>
      <img src={shown.src} alt={shown.caption}/>
      <div className="assembly-row assembly-image-navigation"><button onClick={()=>cycle(-1)} disabled={frames.length<2}>← Previous image</button><span>{frame+1} / {frames.length}{photo?' · Assembly photo':''}</span><button onClick={()=>cycle(1)} disabled={frames.length<2}>Next image →</button></div>
    </dialog>
  </section>
}
function Command({ command }: { command: string }) {
  const [copied,setCopied] = useState(false)
  return <div className="assembly-command"><pre>{command}</pre><button className="assembly-text-button" onClick={async () => {try {await navigator.clipboard.writeText(command);setCopied(true)} catch {setCopied(false)}}}>{copied ? 'Copied ✓' : 'Copy command'}</button></div>
}
const StepVideos = memo(function StepVideos({ step, build }: { step: AssemblyStep; build: Build }) {
  const clips = (step.id==='p37'?['p37','p40']:step.id==='prepare-pp'?['p33']:[step.id]).flatMap(id=>(localClips as Record<string,{src:string;poster:string;title:string;duration:number}[]>)[id] ?? []).filter((_,i)=>step.id==='prepare-pp'?i===0:step.id==='p33'?i===1:true)
  const [active,setActive] = useState(0)
  if (!clips.length) return null
  const clip = clips[active]
  return <section className="assembly-video-section assembly-local-video">
    <div className="assembly-row"><div><span className="assembly-eyebrow">FOLLOW ALONG · THIS STEP</span><h3>{clip.title}</h3></div><span className="assembly-muted">{Math.floor(clip.duration/60)}:{String(clip.duration%60).padStart(2,'0')}</span></div>
    {clips.length>1 && <div className="assembly-clip-tabs">{clips.map((c,i)=><button key={c.src} aria-pressed={active===i} onClick={()=>setActive(i)}>{c.title}</button>)}</div>}
    <video key={clip.src} controls playsInline preload="auto" poster={clip.poster} aria-label={clip.title} src={clip.src}/>
    <p className="assembly-muted">This clip shows an older model of the hand. Use it for the handling technique; follow the instructions and diagrams for your selected {build.side} {build.version} hand.</p>
  </section>
}, (a,b)=>a.step.id===b.step.id&&a.build.side===b.build.side&&a.build.version===b.build.version)

function FeeTechVideos() {
  const [active, setActive] = useState(0)
  const clips = ['Cable connections', 'Installed motor wiring', 'Connector orientation']
  return <section className="assembly-video-section assembly-local-video">
    <span className="assembly-eyebrow">FEETECH · CLOSE-UP VIDEOS</span><h3>{clips[active]}</h3>
    <div className="assembly-clip-tabs">{clips.map((label,i) => <button key={label} aria-pressed={active === i} onClick={() => setActive(i)}>{label}</button>)}</div>
    <video key={active} controls playsInline preload="auto" poster={`./assembly/media/feetech-video-${active+1}-poster.jpg`} aria-label={clips[active]} src={`./assembly/media/feetech-video-${active+1}.mp4`} />
    <p className="assembly-muted">This clip shows an older model of the hand. Power the board off before connecting or disconnecting a FeeTech motor.</p>
  </section>
}

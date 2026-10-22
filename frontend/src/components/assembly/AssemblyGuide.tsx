import {GuideBackgroundEditor} from './GuideBackgroundEditor'
import {GuideText,GuideEditingContext,useGuideEditing} from './GuideEditing'
import {ViewToggle} from './AssemblyComparison'
import {TouchBoardConnection} from './TouchBoardConnection'
import {BoardIdentification} from './BoardIdentification'
import {SpoolOverview} from './SpoolOverview'
import {AssemblyNavigation, chapterTitle} from './AssemblyNavigation'
import {stepTools, buildTools, partsOnly} from './assemblyTools'
import {RoutingInspection} from './RoutingInspection'
import { useRef, useState, type ReactNode } from 'react'
import { lazy, Suspense } from 'react'
import { ThumbPpThreading } from './ThumbPpThreading'
import { TendonPreparation, KnotReinforcement } from './TendonPreparation'
import { FingerMotion } from './FingerMotion'
import { FINGER_CHECKS } from './fingerMovements'
import { DriveExplorer } from './DriveExplorer'
import { CadDetail } from './CadDetail'
import { CAD_DETAILS } from './cadDetails'
import { MotorCheck } from './MotorCheck'
import { MotorChain } from './MotorChain'
import { JointInspection } from './JointInspection'
import { WristRouting } from './WristRouting'
import { ASSEMBLY_MOTIONS } from './assemblyMotions'
import { TendonRouting } from './TendonRouting'
import { HandLabels } from './HandLabels'
import { KnotLesson } from './KnotLesson'
import { CloveHitchLesson } from './CloveHitchLesson'
import { TouchCableWrap } from './TouchCableWrap'
import { TouchScrewGuide } from './TouchScrewGuide'
import {StepMedia} from './StepMedia'
import {StepSupplies} from './StepSupplies'
import { ThreadingAnimation } from './ThreadingAnimation'
import { EMPTY_PROGRESS, changeBuildProgress } from './progress'
import { useAssemblyProgress } from './useAssemblyProgress'
import { buildSteps, commands, FINAL_CHECKS, figures, GLOSSARY, instructions, kit, note, type Build, type Figure } from './buildContent'
import './assembly.css'
import './review.css'

const MOTION_AT:Record<string,number>={p33:0,p42:1,p46:0,p54:0,p62:0,p64:1,p68:1,p89:1,p99:1,p122:1,p123:1,p126:2}
const INSPECTION_AT:Record<string,number>={p33:1,p42:2,p46:2,p54:2,p62:2,p64:2,p68:2,p89:1}
const DETAIL_AT:Record<string,number>={'pp-ready':1,'thumb-pp-ready':1,'finishing-pp':0,p73:1,p98:0,p127:1,p129:1,p139:1}
const PartsExplorer = lazy(() => import('./PartsExplorer').then(m=>({default:m.PartsExplorer})))
export function AssemblyGuide({ onClose, safetyControl }: { onClose: () => void; safetyControl?: ReactNode }) {
  const {progress,setProgress,ready,saveStatus} = useAssemblyProgress()
  const editing=useGuideEditing([progress.build.version,progress.build.side,progress.build.motor,progress.build.audience].join('/'))
  const [query, setQuery] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const [sidebarCollapsed,setSidebarCollapsed] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [glossary, setGlossary] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const main = useRef<HTMLElement>(null)
  const STEPS = buildSteps(progress.build)
  const step = STEPS.find(s => s.id === progress.current) ?? STEPS[0]
  const index = STEPS.indexOf(step)
  const required = STEPS.filter(s=>!s.hint&&s.id!=='p1')
  const completed = required.filter(s=>progress.done.includes(s.id)).length
  const previous = STEPS.slice(0,index).reverse().find(s=>!s.hint)
  const next = STEPS.slice(index+1).find(s=>!s.hint)
  const resume = required.find(s=>s.id===progress.views['hint:return']) ?? previous ?? required[0]
  const done = progress.done.includes(step.id)
  const build = progress.build
  const copy = instructions(step, build)
  const stepFigures = figures(step, build)
  const warning = note(step, build)
  const tools = build.version==='base'&&step.id==='p18'?['Short screw head']:stepTools(step)
  const parts = partsOnly(kit(step,build))
  const equipment = buildTools()
  const checklist = step.id === 'p139' ? FINAL_CHECKS : step.id === 'p45' ? FINGER_CHECKS : []
  const checkKey=(i:number)=>step.id==='p45'?`p45:finger:${i}`:`${step.id}:${i}`
  const allChecked = step.id === 'motor-check' ? Array.from({length:17},(_,i)=>`motor-check:${i+1}`).every(k=>progress.checks.includes(k)) : step.id === 'p83' ? progress.tendons.length === 32 : ['p123','p126'].includes(step.id) ? progress.checks.filter(k=>k.startsWith(`${step.id}:tendon:`)).length===32 : checklist.every((_,i) => progress.checks.includes(checkKey(i)))
  const percent = Math.round(completed / required.length * 100)
  function go(id: string) {
    setQuery('')
    setProgress(p => ({ ...p, current: id, views: STEPS.find(s=>s.id===id)?.hint&&!step.hint ? {...p.views,'hint:return':step.id} : p.views }))
    setNavOpen(false)
    main.current?.scrollTo({ top: 0, behavior: 'instant' })
    requestAnimationFrame(() => heading.current?.focus({ preventScroll: true }))
  }
  function changeBuild(value: Partial<Build>) { setProgress(p=>changeBuildProgress(p,value)) }
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
  const filtered = STEPS.filter(s => `${editing.read(`${s.id}/title`,s.title)} ${s.section??''} ${s.chapter} ${instructions(s,build).map((line,i)=>editing.read(`${s.id}/instruction/${i}`,line)).join(' ')} ${kit(s,build).join(' ')} ${stepTools(s).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase()))
  if (!ready) return <div className="assembly-loading"><p><GuideText variant field="prose/AssemblyGuide.tsx/f764a6be18" text={"Restoring your build…"} label="Guide text"/></p><button className="btn" onClick={onClose}>Close</button></div>
  return <GuideEditingContext.Provider value={editing}><div className="assembly-app" data-version={build.version}>
    <header className="assembly-header">
      <div className="assembly-brand"><i className="assembly-logo" role="img" aria-label="ORCA"/><span>ASSEMBLY WORKSPACE</span></div>
      <div className="assembly-header-actions">
        {safetyControl}

        <button className="assembly-text-button" aria-expanded={glossary} onClick={() => setGlossary(!glossary)}>Parts & terms</button>
        <button className="assembly-close" onClick={onClose} aria-label="Save and close assembly guide">Save & close ×</button>
      </div>
    </header>
    {glossary && <section className="assembly-glossary" aria-label="Parts and terms"><div className="assembly-row"><h2><GuideText variant field="prose/AssemblyGuide.tsx/535bc36505" text={"Know your parts"} label="Section heading"/></h2><button className="assembly-text-button" onClick={() => setGlossary(false)}>Close basics ×</button></div><dl>{GLOSSARY.map(([term,definition]) => <div key={term}><dt><GuideText field={`glossary/${term}/term`} text={term} label="Term"/></dt><dd><GuideText field={`glossary/${term}/definition`} text={definition} label="Definition"/></dd></div>)}</dl></section>}
    <div className={`assembly-layout ${sidebarCollapsed?'is-sidebar-collapsed':''}`}>
      <button className="assembly-mobile-nav" onClick={() => setNavOpen(!navOpen)} aria-expanded={navOpen} aria-controls="assembly-navigation">{navOpen ? 'Close chapters' : `Chapters · ${chapterTitle(step)}`} ☰</button>
      <aside className={`assembly-sidebar ${navOpen ? 'is-open' : ''}`} id="assembly-navigation">
        <AssemblyNavigation steps={STEPS} current={step} done={progress.done} title={s=>editing.read(`${s.id}/title`,s.title)} query={query} filtered={filtered} build={build} onGo={go} beforeContents={<>
                <div className="assembly-progress"><div className="assembly-row"><span>{completed} / {required.length} steps</span><strong>{percent}%</strong></div><progress value={completed} max={required.length} aria-label="Assembly progress" /></div>
        <label className="assembly-search"><span className="assembly-sr-only">Search assembly instructions</span><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Find a part or step…" /></label>
        </>}/>
        <div className="assembly-save-status" role="status">{saveStatus}</div>
        {resetting ? <div className="assembly-reset"><p><GuideText variant field="prose/AssemblyGuide.tsx/a5868c5fbc" text={"Clear assembly progress for a new build?"} label="Guide text"/></p><button onClick={() => { setProgress(EMPTY_PROGRESS); setResetting(false); main.current?.scrollTo(0,0) }}>Clear progress</button><button onClick={() => setResetting(false)}>Cancel</button></div> : <button className="assembly-text-button" onClick={() => setResetting(true)}>Start a new build</button>}
      </aside>
      <main ref={main} className="assembly-main">
        <button className="assembly-sidebar-chevron" aria-label={sidebarCollapsed?'Expand chapters':'Collapse chapters'} title={sidebarCollapsed?'Expand chapters':'Collapse chapters'} aria-expanded={!sidebarCollapsed} aria-controls="assembly-navigation" onClick={()=>setSidebarCollapsed(!sidebarCollapsed)}>{sidebarCollapsed?'›':'‹'}</button>
        <GuideBackgroundEditor step={step.id}/>
        <div className="assembly-breadcrumb"><span>{step.id!=='p1'&&<>{chapterTitle(step)}{step.section?` · ${step.section}`:''}</>}</span><span>{step.id==='p1'?'':step.hint?'HINT · OPTIONAL':`STEP ${String(required.indexOf(step)+1).padStart(2,'0')} / ${required.length}`}</span></div>
        <div className="assembly-step-heading"><h2 ref={heading} tabIndex={-1}><GuideText singleLine field={`${step.id}/title`} text={step.title} label="Step title"/></h2>{step.id!=='p1'&&<StepSupplies key={step.id} step={step.id} build={build} parts={parts} tools={tools}/>}</div>
        {step.id!=='p1'&&build.version==='full'&&(ASSEMBLY_MOTIONS[step.id]||['p23','p35','p45','p80','p83','p115','p123','p126'].includes(step.id))&&<p className="assembly-muted"><GuideText variant field="prose/AssemblyGuide.tsx/4f3cffcb55" text={"Mechanical reference: Base geometry. Full-specific sensor parts are not represented in this model."} label="Guide text"/></p>}
        {step.id==='p23'&&build.motor==='feetech'&&<p className="assembly-muted"><GuideText variant field="prose/AssemblyGuide.tsx/94c60d5ecc" text={"The anatomy reference uses a Dynamixel wrist and tower; use the FeeTech parts for your build."} label="Guide text"/></p>}
        {step.id === 'p1' && <div className="assembly-step-meta assembly-config-chips">
          <label><span className="assembly-sr-only">Hand</span><select aria-label="Hand" value={build.side} onChange={e=>changeBuild({side:e.target.value as Build['side']})}><option value="right">Right hand</option><option value="left">Left hand</option></select></label>
          <label><span className="assembly-sr-only">Motors</span><select aria-label="Motors" value={build.motor} onChange={e=>changeBuild({motor:e.target.value as Build['motor']})}><option value="dynamixel">Dynamixel</option><option value="feetech">FeeTech</option></select></label>
          <label><span className="assembly-sr-only">Version</span><select aria-label="Version" value={build.version} onChange={e=>changeBuild({version:e.target.value as Build['version']})}><option value="base">Base</option><option value="touch">Touch</option><option value="full">Full</option></select></label>
          </div>}
        {step.id === 'p1' && <><Suspense fallback={<p>{"Loading your hand…"}</p>}><PartsExplorer build={build}/></Suspense>{build.version==='touch'&&<p className="assembly-muted"><GuideText variant field="prose/AssemblyGuide.tsx/750d98ce89" text={"Build the fingers and thumb with all skins off. Connect and mount their Touch sensors next, then fit the PP skins before building the hand and tower. Connect the sensor cable tails to the connector board later. Touch uses sensors instead of DP skins."} label="Guide text"/></p>}{build.version==='full'&&<p className="assembly-note"><GuideText variant field="prose/AssemblyGuide.tsx/d6745dd89a" text={"Full-specific sensor installation and harness routing still need a verified procedure before closing the hand."} label="Guide text"/></p>}</>}
        {step.id==='p1'&&<section className="assembly-tool-overview"><h3><GuideText variant field="prose/AssemblyGuide.tsx/f7fe31ffad" text={"Tools"} label="Section heading"/></h3><div className="assembly-tool-columns"><div><h4><GuideText variant field="prose/AssemblyGuide.tsx/5e36900b3e" text={"At the bench"} label="Section heading"/></h4><ul>{equipment.assembly.map((item,i)=><li key={i}><GuideText field={`equipment/assembly/${i}`} text={item} label={`Tool ${i+1}`}/></li>)}</ul></div><div><h4><GuideText variant field="prose/AssemblyGuide.tsx/fb93ba8114" text={"Setup and electronics"} label="Section heading"/></h4><ul>{equipment.setup.map((item,i)=><li key={i}><GuideText field={`equipment/setup/${i}`} text={item} label={`Tool ${i+1}`}/></li>)}</ul></div></div></section>}
        <StepMedia key={`${step.id}-${build.motor}`} step={step.id} build={build}>
        {step.id==='p123'&&<SpoolOverview build={build}/>}
        {step.id === 'p6' && <KnotLesson/>}
        {step.id === 'p23' && <HandLabels build={build}/>}
        {step.id.startsWith('touch-')&&['touch-ids','touch-test'].includes(step.id)&&<table className="assembly-sensor-ids"><caption>Sensor IDs</caption><thead><tr><th scope="col">Finger</th><th scope="col">ID</th></tr></thead><tbody>{['Thumb','Index','Middle','Ring','Pinky'].map((finger,id)=><tr key={finger}><th scope="row">{finger}</th><td>{id}</td></tr>)}</tbody></table>}
        {!['p1','p6','p23'].includes(step.id) && <div className="assembly-guided-content">
          {warning && <div className="assembly-note"><p><GuideText field={`${step.id}/note`} text={warning} label="Step note"/></p></div>}

          <ol className={`assembly-guided-instructions ${build.version==='base'&&step.id==='p29'?'assembly-dp-preparation':''}`}>{copy.map((instruction,i) => {
            const images=stepFigures.filter(f=>(f.instruction??1)===i+1)
            const command=commands(step,build).filter((_,n)=>i===(step.id==='p150'?(n===0?0:2):step.id==='p154'?1:0))
            return <li key={`${step.id}:${i}`} value={i+1} className={build.version==='base'&&step.id==='p26'&&i===2?'assembly-knot-emphasis':undefined}>
              {build.version==='base'&&step.id==='p37'&&i===1&&<KnotReinforcement count={1}/>}
              <p className="assembly-guided-text"><span aria-hidden="true">{i+1}</span><GuideText field={`${step.id}/instruction/${i}`} text={instruction} label={`Instruction ${i+1}`}/></p>
              {command.map(text=><Command key={text} command={text}/>)}
              {images.length>0&&<MediaGallery key={`${step.id}-${build.side}-${build.motor}-${build.version}-${i}`} items={images} focused={-1} saved={progress.views[step.id]} onSelect={src=>setProgress(p=>({...p,views:{...p.views,[step.id]:src}}))}/>}
              {step.id==='p139'&&i===0&&checklist.length > 0 && <section className="assembly-work-checklist"><h3><GuideText variant field="prose/AssemblyGuide.tsx/3d29c4c3a3" text={String(step.id === 'p139' ? 'Final assembly checklist' : 'Finger movement checklist')} label="Section heading"/></h3>{checklist.map((label,i) => <label key={label}><input type="checkbox" checked={progress.checks.includes(checkKey(i))} onChange={() => toggleCheck(checkKey(i))} /><span><GuideText field={`${step.id}/check/${i}`} text={label} label={`Checklist item ${i+1}`}/></span></label>)}</section>}
        {i===1&&step.id==='motor-check'&&<MotorCheck build={build} selected={Number(progress.views['motor-check:selected']??1)} onSelect={id=>setProgress(p=>({...p,views:{...p.views,'motor-check:selected':String(id)}}))} checked={Array.from({length:17},(_,i)=>i+1).filter(id=>progress.checks.includes(`motor-check:${id}`))} onCheck={id=>toggleCheck(`motor-check:${id}`)}/>}
        {i===(build.version==='base'&&step.id==='pp-ready'?0:DETAIL_AT[step.id]??copy.length-1)&&CAD_DETAILS[step.id]&&step.id!=='p46'&&!(build.motor==='feetech'&&CAD_DETAILS[step.id].motorSpecific)&&<CadDetail key={step.id} build={build} step={step.id}/>}
        {build.version==='base'&&step.id==='p26'&&i===2&&<KnotReinforcement count={1}/>}
        {build.version==='base'&&step.id==='p33'&&i===3&&<CadDetail build={build} step="index-dp-skin"/>}
        {build.version==='base'&&step.id==='p42'&&i===0&&<CadDetail build={build} step="index-pp-skin"/>}
        {i===0&&step.id==='p115'&&<MotorChain build={build}/>}
        {i===0&&step.id==='p101'&&<BoardIdentification build={build}/>}
        {build.version!=='base'&&i===1&&['p37','p49','p56'].includes(step.id)&&<KnotReinforcement count={step.id==='p37'?1:3}/>}
        {i===0&&['touch-wrap-short','touch-wrap-long'].includes(step.id)&&<CloveHitchLesson key={step.id}/>}
        {i===1&&step.id==='touch-wrap-short'&&<TouchCableWrap/>}
        {i===1&&step.id==='touch-board-link'&&<TouchBoardConnection/>}
        {i===1&&step.id==='touch-mount'&&<TouchScrewGuide build={build}/>}
        {i===1&&['p26','thumb-tendons'].includes(step.id) && <TendonPreparation/>}
        {i===1&&step.id==='thumb-tendons'&&<KnotLesson/>}
        {i===2&&step.id==='thumb-tendons'&&<KnotReinforcement count={1}/>}
        {build.version!=='base'&&step.id==='thumb-pp'&&i===0&&<ThumbPpThreading build={build}/>}
        {build.version!=='base'&&i===1&&step.id==='thumb-pp'&&<><TendonPreparation/><KnotReinforcement count={1}/></>}
        {i===0&&step.id === 'p59' && <TendonRouting step={step.id} build={build}/>}
        {i===1&&step.id === 'p77' && <WristRouting build={build} routeIndex={Number(progress.views['p77:route']??0)} onRoute={index=>setProgress(p=>({...p,views:{...p.views,'p77:route':String(index)}}))}/>}
        {i===0&&step.id === 'p80' && <RoutingInspection build={build}/>}
        {i===(step.id==='p35'?1:2)&&['p35','p45'].includes(step.id) && <FingerMotion build={build} wholeIndex={step.id==='p35'}/>}

        {i===(build.version==='base'&&step.id==='p42'?1:MOTION_AT[step.id]??copy.length-1)&&ASSEMBLY_MOTIONS[step.id] && step.id!=='p93' && !(build.motor==='feetech'&&ASSEMBLY_MOTIONS[step.id].motorSpecific) && <ThreadingAnimation key={`motion:${step.id}`} kind={step.animation??'straight'} build={build} step={step.id} />}
        {i===(build.version==='base'&&step.id==='p42'?3:INSPECTION_AT[step.id])&&<JointInspection build={build} step={step.id}/>}
        {i===(step.id==='p83'?1:3)&&['p83','p123','p126'].includes(step.id)&&<DriveExplorer key={`drive:${step.id}`} build={build} stage={step.id==='p83'?'wrist':step.id==='p123'?'bottom':'top'} checked={step.id==='p83'?progress.tendons:progress.checks.filter(k=>k.startsWith(`${step.id}:tendon:`)).map(k=>Number(k.split(':').at(-1)))} onCheck={i=>setProgress(p=>step.id==='p83'?({...p,tendons:p.tendons.includes(i)?p.tendons.filter(n=>n!==i):[...p.tendons,i],done:p.done.filter(id=>id!==step.id)}):({...p,checks:p.checks.includes(`${step.id}:tendon:${i}`)?p.checks.filter(k=>k!==`${step.id}:tendon:${i}`):[...p.checks,`${step.id}:tendon:${i}`],done:p.done.filter(id=>id!==step.id)}))}/>}

            </li>
          })}</ol>

          {step.id === 'p141' && <button className="assembly-primary" onClick={onClose}>Return to Setup</button>}
        </div>}

        </StepMedia>
        {build.version==='base'&&step.id==='p139'&&<p className="assembly-setup-continuation"><GuideText field="p139/setup-continuation" text="Continue with tensioning, calibration and the test stages in the same Setup tab in ORCA UI." label="Continue in Setup"/></p>}
        {step.id!=='p139'&&checklist.length > 0 && <section className="assembly-work-checklist"><h3><GuideText variant field="prose/AssemblyGuide.tsx/3d29c4c3a3" text={String(step.id === 'p139' ? 'Final assembly checklist' : 'Finger movement checklist')} label="Section heading"/></h3>{checklist.map((label,i) => <label key={label}><input type="checkbox" checked={progress.checks.includes(checkKey(i))} onChange={() => toggleCheck(checkKey(i))} /><span><GuideText field={`${step.id}/check/${i}`} text={label} label={`Checklist item ${i+1}`}/></span></label>)}</section>}

        <footer className="assembly-footer"><button className="assembly-secondary" disabled={!previous} onClick={() => previous && go(previous.id)}>← Previous</button>{step.id!=='p1'&&step.id!=='p45'&&!step.hint&&<button className="assembly-secondary assembly-completion" aria-pressed={done} disabled={!done&&!allChecked} onClick={toggleDone}>{done?'Completed ✓':'Mark complete'}</button>}{!(build.version==='base'&&step.id==='p139')&&<button className="assembly-primary" disabled={!step.hint&&!next} onClick={() => step.hint?go(resume.id):next&&go(next.id)}>{step.hint?'Return to assembly →':'Next step →'}</button>}</footer>

      </main>
    </div>
  </div></GuideEditingContext.Provider>
}

const isModelImage=(src:string)=>/\/(renders|parts|molds)\//.test(src)
function MediaGallery({ items, saved, onSelect, focused }: { items: Figure[]; focused:number; saved?: string; onSelect: (src: string) => void }) {
  const [selected,setSelected]=useState(Math.max(0,items.findIndex(item=>item.src===saved)))
  const [photo,setPhoto]=useState(false)
  const [inlinePhotos,setInlinePhotos]=useState<Record<string,boolean>>({})
  const dialog=useRef<HTMLDialogElement>(null)
  const item=items[selected],shown=photo&&item.photo?item.photo:item
  const frames=items.flatMap((item,i)=>item.photo?[{i,photo:false},{i,photo:true}]:[{i,photo:false}])
  const frame=frames.findIndex(f=>f.i===selected&&f.photo===photo)
  function cycle(direction:number){const next=frames[(frame+direction+frames.length)%frames.length];setSelected(next.i);setPhoto(next.photo);onSelect(items[next.i].src)}
  function enlarge(index:number){setSelected(index);setPhoto(Boolean(inlinePhotos[items[index].src]));onSelect(items[index].src);dialog.current?.showModal()}
  return <section className="assembly-panel-gallery" style={{'--panel-columns':items.length===1?1:Math.min(5,Math.max(2,Math.ceil(items.length/2))) } as React.CSSProperties} aria-label="Assembly photos and diagrams">
    {items.map((item,i)=>{
      const isPhoto=Boolean(inlinePhotos[item.src]&&item.photo),view=isPhoto?item.photo!:item
      return <figure key={item.src} data-contrast={isPhoto?false:item.contrast??false} data-wide={item.wide||undefined} className={focused<0?'':(item.instruction??i+1)===focused+1?'is-focused':'is-unfocused'}>
        <div className="assembly-row" style={{justifyContent:item.photo?'space-between':'flex-end'}}>{item.photo&&<ViewToggle photo={isPhoto} onChange={photo=>setInlinePhotos(p=>({...p,[item.src]:photo}))}/>}<button className="assembly-text-button" onClick={()=>enlarge(i)} aria-label={`Enlarge image ${i+1}`}>⤢</button></div>
        <div className="assembly-image-frame">
          <button className="assembly-image-button" data-image-kind={isModelImage(view.src)?'cad':'photo'} onClick={()=>enlarge(i)} aria-label={`Enlarge detail ${i+1}`}><img key={view.src} src={view.src} alt={view.caption} loading="lazy" onLoad={e=>{if(!isModelImage(view.src))e.currentTarget.style.maxWidth=`min(100%, ${e.currentTarget.naturalWidth}px)`}}/></button>
        </div>{item.showCaption&&<figcaption className="assembly-panel-caption"><GuideText field={`caption/${view.src}`} text={view.caption} label="Image caption"/></figcaption>}
      </figure>
    })}
    <dialog ref={dialog} className="assembly-lightbox assembly-comparison" data-contrast={photo?false:item.contrast??false} data-image-kind={isModelImage(shown.src)?'cad':'photo'} aria-label="Enlarged assembly image" onKeyDown={e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();cycle(e.key==='ArrowRight'?1:-1)}}} onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}>
      <div className="assembly-row"><span>Instruction {item.instruction??selected+1}</span>{item.photo&&<ViewToggle photo={photo} onChange={setPhoto}/>}<button autoFocus onClick={()=>dialog.current?.close()}>Close image ×</button></div>
      <img key={shown.src} src={shown.src} alt={shown.caption} onLoad={e=>{if(!isModelImage(shown.src))e.currentTarget.style.maxWidth=`min(100%, ${e.currentTarget.naturalWidth}px)`}}/>{item.showCaption&&<p className="assembly-lightbox-caption"><GuideText field={`caption/${shown.src}`} text={shown.caption} label="Image caption"/></p>}
      <div className="assembly-row assembly-image-navigation"><button onClick={()=>cycle(-1)} disabled={frames.length<2}>← Previous image</button><span>{frame+1} / {frames.length}{photo?' · Assembly photo':''}</span><button onClick={()=>cycle(1)} disabled={frames.length<2}>Next image →</button></div>
    </dialog>
  </section>
}
function Command({ command }: { command: string }) {
  const [copied,setCopied] = useState(false)
  return <div className="assembly-command"><pre>{command}</pre><button className="assembly-text-button" onClick={async () => {try {await navigator.clipboard.writeText(command);setCopied(true)} catch {setCopied(false)}}}>{copied ? 'Copied ✓' : 'Copy command'}</button></div>
}

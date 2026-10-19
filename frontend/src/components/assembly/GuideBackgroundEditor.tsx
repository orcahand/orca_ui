import {GuideColorWheel} from './GuideColorWheel'
import {useContext,useEffect,useRef,useState} from 'react'
import {GuideEditingContext} from './GuideEditing'

const PRESETS=[['White','#ffffff'],['Warm paper','#f6f5f0'],['Soft grey','#e8e9e5'],['Sage','#93a69a'],['Dark sage','#70877a'],['Charcoal','#29343c']] as const
// These are the surfaces that actually paint behind transparent renders/canvases.
const SURFACES='.assembly-image-button,.assembly-joint-motion,.assembly-model-controls-frame,.assembly-finger-preview,.assembly-anatomy-viewport,.assembly-screw-model,.assembly-area-canvas,.assembly-area-scroll,.assembly-cad-detail-canvas,.assembly-hand-label-render,[class*="-canvas"]'
const TARGETS=`${SURFACES},.assembly-main,.assembly-sidebar,.assembly-hand-navigation,.assembly-contents-scroll,.assembly-header,section,figure,.assembly-image-frame,.assembly-note,.assembly-supplies,.assembly-tool-overview,.assembly-check,.assembly-app`
const NAMES:Record<string,string>={'assembly-main':'Page','assembly-sidebar':'Sidebar','assembly-hand-navigation':'Hand panel','assembly-contents-scroll':'Contents','assembly-image-button':'Image background','assembly-image-frame':'Image background','assembly-joint-motion':'Model background','assembly-model-controls-frame':'Model background','tag-figure':'Illustration','tag-section':'Section'}
function selector(name:string){return /^tag-(figure|section|dialog)$/.test(name)?name.slice(4):/^assembly-[\w-]+$/.test(name)?`.${name}`:null}
const GLOBAL=['assembly-app','assembly-main','assembly-sidebar','assembly-hand-navigation','assembly-contents-scroll','assembly-header']
export function GuideBackgroundEditor({step}:{step:string}){
 const editing=useContext(GuideEditingContext)!,panel=useRef<HTMLDivElement>(null)
 const [open,setOpen]=useState(false),[picking,setPicking]=useState(false),[selected,setSelected]=useState(''),[color,setColor]=useState('#f6f5f0')
 const root=()=>panel.current?.closest<HTMLElement>('.assembly-app')??null
 function select(element:HTMLElement){
  const name=Array.from(element.classList).find(c=>c.startsWith('assembly-'))??`tag-${element.tagName.toLowerCase()}`
  const query=selector(name);if(!query)return
  const app=root()!,global=GLOBAL.includes(name),container=global?app:app.querySelector('.assembly-main')!
  const index=name==='assembly-app'?0:Array.from(container.querySelectorAll(query)).indexOf(element)
  const key=[global?'global':editing.scope,global?'global':step,name,index].join('::')
  setSelected(key)
  setPicking(false)
  const rgb=getComputedStyle(element).backgroundColor.match(/[\d.]+/g)
  setColor(editing.draft.backgrounds[key]??(rgb&&rgb.length>=3&&rgb[3]!=='0'?'#'+rgb.slice(0,3).map(v=>Math.round(+v).toString(16).padStart(2,'0')).join(''):'#f6f5f0'))
 }
 useEffect(()=>{setSelected('');setPicking(false);setOpen(false)},[step,editing.scope])
 useEffect(()=>{
  const app=root();if(!app||!picking)return
  const choose=(e:MouseEvent)=>{if(panel.current?.contains(e.target as Node))return;e.preventDefault();e.stopPropagation();const el=(e.target as Element).closest<HTMLElement>(TARGETS);if(el&&app.contains(el)){select(el);setPicking(false)}}
  app.addEventListener('click',choose,true);app.classList.add('assembly-picking-background')
  return()=>{app.removeEventListener('click',choose,true);app.classList.remove('assembly-picking-background')}
 },[picking,step,editing])
 useEffect(()=>{
  const app=root();if(!app)return
  const originals=new Map<HTMLElement,Map<string,{value:string;priority:string}>>()
  function set(el:HTMLElement,property:string,value:string){
   let saved=originals.get(el);if(!saved){saved=new Map();originals.set(el,saved)}
   if(!saved.has(property))saved.set(property,{value:el.style.getPropertyValue(property),priority:el.style.getPropertyPriority(property)})
   el.style.setProperty(property,value,'important')
  }
  function resolve(key:string){
   const [scope,page,name,index]=key.split('::');if(scope!=='global'&&(scope!==editing.scope||page!==step))return null
   const query=selector(name);if(!query)return null
   const container=scope==='global'?app:app!.querySelector('.assembly-main')
   return name==='assembly-app'?app:container?.querySelectorAll<HTMLElement>(query)[Number(index)]??null
  }
  function apply(){
   const entries=Object.entries(editing.draft.backgrounds).map(([key,color])=>({key,color,el:resolve(key)})).filter(entry=>entry.el)
   // Apply containing cards before individual surfaces so specific choices win.
   entries.sort((a,b)=>a.el===b.el?0:a.el!.contains(b.el)?-1:b.el!.contains(a.el)?1:0)
   for(const {key,color,el} of entries){
    const surfaces=[el!,...(!key.startsWith('global::')?el!.querySelectorAll<HTMLElement>(SURFACES):[])]
    for(const surface of surfaces){set(surface,'background-color',color);set(surface,'background-image','none');if(!key.startsWith('global::'))set(surface,'--assembly-image-bg',color)}
   }
  }
  apply();const observer=new MutationObserver(apply);observer.observe(app,{childList:true,subtree:true})
  return()=>{observer.disconnect();for(const [el,properties] of originals)for(const [property,original] of properties){if(original.value)el.style.setProperty(property,original.value,original.priority);else el.style.removeProperty(property)}}
 },[editing.draft.backgrounds,editing.scope,step])
 useEffect(()=>{
  const app=root();if(!app||!selected||!open)return
  const [scope,,name,index]=selected.split('::'),query=selector(name);if(!query)return
  const container=scope==='global'?app:app.querySelector('.assembly-main')
  const el=name==='assembly-app'?app:container?.querySelectorAll<HTMLElement>(query)[Number(index)]
  el?.classList.add('assembly-background-selected')
  return()=>el?.classList.remove('assembly-background-selected')
 },[selected,open,step])

 function paint(value:string){setColor(value);if(selected)editing.background(selected,value)}
 const name=selected.split('::')[2],label=NAMES[name]??name?.replace('assembly-','').replaceAll('-',' ')
 function toggle(){if(!open&&!selected){const main=root()?.querySelector<HTMLElement>('.assembly-main');if(main)select(main)}setOpen(!open);setPicking(false)}
 return <div ref={panel} className={`assembly-editor-controls ${open?'is-color-open':''}`}>
  <div className="assembly-row"><span role="status">{editing.error||'Edits save automatically in this browser. Export to share.'}</span><div><button className="assembly-text-button" aria-expanded={open} onClick={toggle}>Background colors</button><button className="assembly-text-button" onClick={editing.exportEdits}>Export edits</button></div></div>
  {open&&picking&&<div className="assembly-color-pick-message" role="status">Click the picture, model or panel background to edit.<button className="assembly-text-button" onClick={()=>setPicking(false)}>Cancel selection</button></div>}
  {open&&!picking&&<div className="assembly-color-panel">
   <div className="assembly-row"><strong>{label?`Editing: ${label}`:'Choose a background'}</strong><button className="assembly-secondary" aria-pressed={picking} onClick={()=>setPicking(!picking)}>{picking?'Cancel selection':'Pick an area'}</button></div>
   <div className="assembly-color-targets">{[['Page','assembly-main'],['Sidebar','assembly-sidebar'],['Hand panel','assembly-hand-navigation'],['Contents','assembly-contents-scroll']].map(([title,name])=><button key={name} className="assembly-secondary" aria-pressed={selected.split('::')[2]===name} onClick={()=>{const el=root()?.querySelector<HTMLElement>(`.${name}`);if(el)select(el)}}>{title}</button>)}</div>
   <GuideColorWheel value={color} onChange={paint} disabled={!selected}/>
   <label className="assembly-color-picker">Custom color<input aria-label="Background color picker" type="color" value={/^#[0-9a-f]{6}$/i.test(color)?color:"#ffffff"} disabled={!selected} onChange={e=>paint(e.target.value)}/><input aria-label="Background hex color" value={color} disabled={!selected} onChange={e=>{setColor(e.target.value);if(/^#[0-9a-f]{6}$/i.test(e.target.value))paint(e.target.value)}} maxLength={7}/><button className="assembly-text-button" disabled={!/^#[0-9a-f]{6}$/i.test(color)} onClick={()=>editing.saveColor(color)}>Save color</button>{selected&&<button className="assembly-text-button" onClick={()=>editing.background(selected,null)}>Restore background</button>}</label>
   <div className="assembly-color-swatches" aria-label="Color presets">{PRESETS.map(([name,value])=><button key={name} title={name} aria-label={`Use ${name} background`} disabled={!selected} onClick={()=>paint(value)}><i style={{backgroundColor:value}}/>{name}</button>)}</div>
   {editing.draft.colors.length>0&&<><p>Saved colors</p><div className="assembly-color-swatches">{editing.draft.colors.map(value=><button key={value} title={value} aria-label={`Use saved ${value}`} disabled={!selected} onClick={()=>paint(value)}><i style={{backgroundColor:value}}/>{value}</button>)}</div></>}
  </div>}
 </div>
}

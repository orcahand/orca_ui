import {createContext,useContext,useLayoutEffect,useRef,useState} from 'react'
import {sameGuideSource} from './guideLabel'

const KEY='orca-ui.assembly.editor.v1'
type Entry={source:string;value:string}
type ListItem={id:string;text:string}
type ListEntry={source:string;items:ListItem[]}
type Draft={text:Record<string,Entry>;lists:Record<string,ListEntry>;backgrounds:Record<string,string>;colors:string[]}
const empty:Draft={text:{},lists:{},backgrounds:{},colors:[]}
function load():Draft{
 try{const v=JSON.parse(localStorage.getItem(KEY)??'null');return {text:Object.fromEntries(Object.entries(v?.text??{}).filter(([,e])=>e&&typeof (e as Entry).source==='string'&&typeof (e as Entry).value==='string')) as Draft['text'],lists:Object.fromEntries(Object.entries(v?.lists??{}).filter(([,entry])=>{
  const e=entry as ListEntry|null
  return e&&typeof e.source==='string'&&Array.isArray(e.items)&&e.items.every(item=>item&&typeof item.id==='string'&&typeof item.text==='string')&&new Set(e.items.map(item=>item.id)).size===e.items.length
 })) as Draft['lists'],backgrounds:Object.fromEntries(Object.entries(v?.backgrounds??{}).filter(([,c])=>typeof c==='string'&&/^#[0-9a-f]{6}$/i.test(c))) as Draft['backgrounds'],colors:(v?.colors??[]).filter((c:unknown)=>typeof c==='string'&&/^#[0-9a-f]{6}$/i.test(c))}}catch{return empty}
}
export function useGuideEditing(scope:string){
 const [draft,setDraft]=useState<Draft>(load),[error,setError]=useState('')
 function update(next:Draft){setDraft(next);try{localStorage.setItem(KEY,JSON.stringify(next));setError('')}catch{setError('Unable to save locally. Export your edits before closing.')}}
 const key=(field:string)=>`${scope}/${field}`
 function matchingFields(field:string,source:string,variant:boolean){
  const current=key(field),prefix=current.slice(0,current.lastIndexOf('/')+1)
  return Object.keys(draft.text).filter(k=>(k===current||(variant&&k.startsWith(prefix)))&&sameGuideSource(draft.text[k].source,source))
 }
 const read=(field:string,source:string,variant=false)=>{
  const entry=draft.text[key(field)]
  if(entry&&sameGuideSource(entry.source,source))return entry.value
  const previous=variant?matchingFields(field,source,true).at(-1):undefined
  return previous?draft.text[previous].value:source
 }
 function write(field:string,source:string,value:string,variant=false){const text={...draft.text};for(const k of matchingFields(field,source,variant))delete text[k];if(source!==value)text[key(field)]={source,value};update({...draft,text})}
 function readList(field:string,source:string[]):ListItem[]{
  const saved=draft.lists[key(field)]
  if(saved){
   try{
    const previous:unknown=JSON.parse(saved.source)
    if(Array.isArray(previous)&&previous.length===source.length&&previous.every((text,i)=>typeof text==='string'&&sameGuideSource(text,source[i])))
     return saved.items.map(item=>/^\d+$/.test(item.id)&&source[Number(item.id)]!==undefined?{...item,text:source[Number(item.id)]}:item)
   }catch{/* Ignore stale or malformed list sources. */}
  }
  return source.map((text,i)=>({id:String(i),text}))
 }
 function writeList(field:string,source:string[],items:ListItem[]|null){const lists={...draft.lists};if(items)lists[key(field)]={source:JSON.stringify(source),items};else delete lists[key(field)];update({...draft,lists})}
 const listText=(field:string,source:string[])=>readList(field,source).map(item=>read(`${field}/${item.id}`,item.text))
 function background(field:string,color:string|null){const backgrounds={...draft.backgrounds};if(color)backgrounds[field]=color;else delete backgrounds[field];update({...draft,backgrounds})}
 function saveColor(color:string){update({...draft,colors:[...new Set([...draft.colors,color])]})}
 function exportEdits(){const url=URL.createObjectURL(new Blob([JSON.stringify({format:'orca-assembly-editor-v1',...draft},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='orca-assembly-edits.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 return {draft,read,write,readList,writeList,listText,background,saveColor,exportEdits,error,scope}
}
type Editing=ReturnType<typeof useGuideEditing>
export const GuideEditingContext=createContext<Editing|null>(null)
function sourceKey(text:string){let h=2166136261;for(let i=0;i<text.length;i++)h=Math.imul(h^text.charCodeAt(i),16777619);return (h>>>0).toString(36)}
export function GuideText({field,text,label,variant=false}:{field:string;text:string;label?:string;variant?:boolean}){
 if(variant)field+=`/${sourceKey(text)}`
 const editing=useContext(GuideEditingContext),ref=useRef<HTMLTextAreaElement>(null),value=editing?.read(field,text,variant)??text
 useLayoutEffect(()=>{const el=ref.current;if(!el)return;const fit=()=>{el.style.height='0';el.style.height=`${el.scrollHeight+2}px`};fit();const observer=new ResizeObserver(()=>{if(el.clientWidth!==Number(el.dataset.width)){el.dataset.width=String(el.clientWidth);fit()}});observer.observe(el);return()=>observer.disconnect()},[value])
 if(!editing)return <>{text}</>
 return <span className="assembly-edit-field"><textarea ref={ref} rows={1} aria-label={label??`Edit ${field}`} value={value} onClick={e=>e.stopPropagation()} onKeyDown={e=>e.stopPropagation()} onChange={e=>editing.write(field,text,e.target.value,variant)}/>{value!==text&&<button type="button" className="assembly-edit-undo" aria-label={`Restore ${label??field}`} title="Restore original text" onClick={e=>{e.preventDefault();editing.write(field,text,text,variant)}}>↶</button>}</span>
}

export function GuideBulletList({field,items,label,emptyText}:{field:string;items:string[];label:string;emptyText?:string}){
 const editing=useContext(GuideEditingContext),root=useRef<HTMLDivElement>(null),focus=useRef<string|null>(null)
 const rows=editing?.readList(field,items)??items.map((text,i)=>({id:String(i),text}))
 useLayoutEffect(()=>{
  if(focus.current===null)return
  const row=Array.from(root.current?.querySelectorAll<HTMLElement>('[data-bullet-id]')??[]).find(el=>el.dataset.bulletId===focus.current)
  const target=row?.querySelector('textarea')??root.current?.querySelector<HTMLButtonElement>('.assembly-list-add')
  target?.focus()
  focus.current=null
 },[rows])
 function add(after?:number){
  const item={id:`added-${crypto.randomUUID?.()??`${Date.now()}-${Math.random().toString(36).slice(2)}`}`,text:''},next=[...rows],index=after===undefined?rows.length:after+1
  next.splice(index,0,item);focus.current=item.id;editing?.writeList(field,items,next)
 }
 function remove(index:number){focus.current=rows[index+1]?.id??rows[index-1]?.id??'';editing?.writeList(field,items,rows.filter((_,i)=>i!==index))}
 const changed=rows.length!==items.length||rows.some((row,i)=>row.id!==String(i))
 return <div ref={root} className="assembly-edit-list">
  {rows.length?<ul aria-label={label}>{rows.map((row,i)=><li key={row.id} data-bullet-id={row.id}><div className="assembly-edit-list-row"><GuideText field={`${field}/${row.id}`} text={row.text} label={`${label} bullet ${i+1}`}/>{editing&&<span className="assembly-list-item-actions"><button type="button" aria-label={`Add bullet after ${label} bullet ${i+1}`} title="Add bullet below" onClick={()=>add(i)}>+</button><button type="button" aria-label={`Remove ${label} bullet ${i+1}`} title="Remove bullet" onClick={()=>remove(i)}>−</button></span>}</div></li>)}</ul>:emptyText?<p>{emptyText}</p>:null}
  {editing&&<div className="assembly-list-actions"><button type="button" className="assembly-text-button assembly-list-add" aria-label={`Add bullet to ${label}`} onClick={()=>add()}>+ Add bullet</button>{changed&&<button type="button" className="assembly-text-button" aria-label={`Reset ${label} list`} title="Restore original bullets and keep their text edits" onClick={()=>editing.writeList(field,items,null)}>Reset list</button>}</div>}
 </div>
}

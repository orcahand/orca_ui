import {createContext,useContext,useLayoutEffect,useRef,useState} from 'react'

const KEY='orca-ui.assembly.editor.v1'
type Entry={source:string;value:string}
type Draft={text:Record<string,Entry>;backgrounds:Record<string,string>;colors:string[]}
const empty:Draft={text:{},backgrounds:{},colors:[]}
function load():Draft{
 try{const v=JSON.parse(localStorage.getItem(KEY)??'null');return {text:Object.fromEntries(Object.entries(v?.text??{}).filter(([,e])=>e&&typeof (e as Entry).source==='string'&&typeof (e as Entry).value==='string')) as Draft['text'],backgrounds:Object.fromEntries(Object.entries(v?.backgrounds??{}).filter(([,c])=>typeof c==='string'&&/^#[0-9a-f]{6}$/i.test(c))) as Draft['backgrounds'],colors:(v?.colors??[]).filter((c:unknown)=>typeof c==='string'&&/^#[0-9a-f]{6}$/i.test(c))}}catch{return empty}
}
export function useGuideEditing(scope:string){
 const [draft,setDraft]=useState<Draft>(load),[error,setError]=useState('')
 function update(next:Draft){setDraft(next);try{localStorage.setItem(KEY,JSON.stringify(next));setError('')}catch{setError('Unable to save locally. Export your edits before closing.')}}
 const key=(field:string)=>`${scope}/${field}`
 const read=(field:string,source:string)=>draft.text[key(field)]?.source===source?draft.text[key(field)].value:source
 function write(field:string,source:string,value:string){const text={...draft.text};if(source===value)delete text[key(field)];else text[key(field)]={source,value};update({...draft,text})}
 function background(field:string,color:string|null){const backgrounds={...draft.backgrounds};if(color)backgrounds[field]=color;else delete backgrounds[field];update({...draft,backgrounds})}
 function saveColor(color:string){update({...draft,colors:[...new Set([...draft.colors,color])]})}
 function exportEdits(){const url=URL.createObjectURL(new Blob([JSON.stringify({format:'orca-assembly-editor-v1',...draft},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='orca-assembly-edits.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 return {draft,read,write,background,saveColor,exportEdits,error,scope}
}
type Editing=ReturnType<typeof useGuideEditing>
export const GuideEditingContext=createContext<Editing|null>(null)
function sourceKey(text:string){let h=2166136261;for(let i=0;i<text.length;i++)h=Math.imul(h^text.charCodeAt(i),16777619);return (h>>>0).toString(36)}
export function GuideText({field,text,label,variant=false,singleLine=false}:{field:string;text:string;label?:string;variant?:boolean;singleLine?:boolean}){
 if(variant)field+=`/${sourceKey(text)}`
 const editing=useContext(GuideEditingContext),ref=useRef<HTMLTextAreaElement>(null),wrapper=useRef<HTMLSpanElement>(null),input=useRef<HTMLInputElement>(null),value=editing?.read(field,text)??text
 const [heading,setHeading]=useState(label==='Section heading'||label==='Step title')
 singleLine=singleLine||heading
 useLayoutEffect(()=>{if(wrapper.current?.closest('h1,h2,h3,h4,h5,h6'))setHeading(true)},[])
 useLayoutEffect(()=>{const el=input.current;if(!el)return;const fit=()=>{el.style.fontSize='';const style=getComputedStyle(el),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');if(!ctx)return;ctx.font=style.font;const width=ctx.measureText(value).width,available=el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-2;if(width>available&&available>0)el.style.fontSize=`${parseFloat(style.fontSize)*available/width}px`};fit();const observer=new ResizeObserver(fit);observer.observe(el);return()=>observer.disconnect()},[value,singleLine])
 useLayoutEffect(()=>{const el=ref.current;if(!el)return;const fit=()=>{el.style.height='0';el.style.height=`${el.scrollHeight+2}px`};fit();const observer=new ResizeObserver(()=>{if(el.clientWidth!==Number(el.dataset.width)){el.dataset.width=String(el.clientWidth);fit()}});observer.observe(el);return()=>observer.disconnect()},[value,singleLine])
 if(!editing)return <>{text}</>
 const props={ 'aria-label':label??`Edit ${field}`,value,onClick:(e:React.MouseEvent)=>e.stopPropagation(),onKeyDown:(e:React.KeyboardEvent)=>e.stopPropagation(),onChange:(e:React.ChangeEvent<HTMLInputElement|HTMLTextAreaElement>)=>editing.write(field,text,e.target.value) }
 return <span ref={wrapper} className="assembly-edit-field">{singleLine?<input ref={input} type="text" {...props}/>:<textarea ref={ref} rows={1} {...props}/>} {value!==text&&<button type="button" className="assembly-edit-undo" aria-label={`Restore ${label??field}`} title="Restore original text" onClick={e=>{e.preventDefault();editing.write(field,text,text)}}>↶</button>}</span>
}

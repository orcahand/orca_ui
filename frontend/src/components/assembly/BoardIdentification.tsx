import {GuideText} from './GuideEditing'
import {useRef,useState} from 'react'
import type {Build} from './buildContent'

// Coordinates are on the unmodified board photograph, displayed 90° counterclockwise.
// The complete STEP omits the USB, power and fan sockets, so use the actual board here.
const PORTS=[
 {id:'board',name:'Connector board',boxes:[[190,40,205,160]],text:'Four-pin socket labeled Sensing. The Touch connector board connects here with its four-wire cable.'},
 {id:'feetech',name:'FeeTech motors',boxes:[[398,38,192,150]],text:'Three-pin FeeTech output, labeled FTH. Use the matching FeeTech board-to-motor cable.'},
 {id:'dynamixel',name:'Dynamixel motors',boxes:[[603,48,197,162]],text:'Three-pin Dynamixel output. Use the matching Dynamixel motor cable.'},
 {id:'fans',name:'Two fans',boxes:[[60,205,245,145],[60,350,245,165]],text:'One plug for each fan. These two sockets are separate from the motor and connector-board outputs.'},
 {id:'usb',name:'USB-C data',boxes:[[898,285,155,190]],text:'Connect the computer with a USB-C data cable when the setup step asks for it.'},
 {id:'power',name:'12 V input',boxes:[[710,500,225,330]],text:'Connect the specified 12 V supply here. Keep the board switch off while changing any connections.'},
 {id:'switch',name:'Power switch',boxes:[[495,520,220,305]],text:'Set the rocker to 0 (off) before adding or removing cables. I is the on position.'},
] as const

export function BoardIdentification({build}:{build:Build}){
 const [selected,setSelected]=useState<string>(build.motor),dialog=useRef<HTMLDialogElement>(null)
 const port=PORTS.find(p=>p.id===selected)!
 const drawing=<svg viewBox="0 0 1152 864" role="img" aria-label={`OH board: ${port.name} highlighted`}>
  <image href="./assembly/details/oh-board-reference.jpeg" width="864" height="1152" transform="translate(0 864) rotate(-90)"/>
  {PORTS.map((p,i)=><g key={p.id} className={p.id===selected?'selected':''} role="button" tabIndex={0} aria-label={`Locate ${p.name}`} aria-pressed={p.id===selected} onClick={()=>setSelected(p.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(p.id)}}}>
   <title>{p.name}</title>{p.boxes.map(([x,y,w,h],j)=><rect key={j} x={x} y={y} width={w} height={h} rx="10"/>)}
   <g transform={`translate(${p.boxes[0][0]+p.boxes[0][2]-12} ${p.boxes[0][1]+12})`}><circle r="22"/><text textAnchor="middle" dy=".35em">{i+1}</text></g>
  </g>)}
 </svg>
 return <section className="assembly-board-identification" aria-label="Identify the OH board connections" data-contrast={false}>
  <div className="assembly-row"><div><h3><GuideText variant field="prose/BoardIdentification.tsx/a3bbf8574b" text={"The OH control board"} label="Section heading"/></h3></div><button className="assembly-text-button" aria-label="Enlarge the board connections" onClick={()=>dialog.current?.showModal()}>⤢</button></div>
  <div className="assembly-board-identification-layout"><div className="assembly-board-photo">{drawing}</div><div>
   <div className="assembly-board-port-list">{PORTS.map((p,i)=><button key={p.id} aria-pressed={p.id===selected} onClick={()=>setSelected(p.id)}><span>{i+1}</span>{p.name}{p.id===build.motor&&<small><GuideText variant field="prose/BoardIdentification.tsx/3866a08fa3" text={"Your motor output"} label="Guide text"/></small>}</button>)}</div>
   <p className="assembly-board-port-description" aria-live="polite"><GuideText variant field="prose/BoardIdentification.tsx/f28fd5d23e" text={[String(port.name),String(port.text)].join('').trim()} label="Guide text"/></p>
  </div></div>
  <dialog ref={dialog} className="assembly-lightbox assembly-board-port-dialog" aria-label="OH board connections" onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}>
   <div className="assembly-row"><span>{port.name}</span><button autoFocus onClick={()=>dialog.current?.close()}>Close image ×</button></div>
   {drawing}<p><GuideText variant field="prose/BoardIdentification.tsx/c70667fee7" text={String(port.text)} label="Guide text"/></p>
  </dialog>
 </section>
}

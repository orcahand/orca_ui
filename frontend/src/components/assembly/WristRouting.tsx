import {useRef,useState} from 'react'
import views from './cad-route-views.json'
import type {Build} from './buildContent'

export function WristRouting({build}:{build:Build}){
 const [palm,setPalm]=useState(true),[channel,setChannel]=useState(0),dialog=useRef<HTMLDialogElement>(null)
 const key=`${build.version}-${build.side}-dynamixel/route-p77-groups`
 const cad=(views as Record<string,{width:number;height:number;points:number[][]}>)[key]
 const color=palm?'#188b9a':'#c05d43',width=cad?.width??1470,height=cad?.height??678
 const row=cad?Array.from({length:16},(_,i)=>i+(palm?16:0)).sort((a,b)=>cad.points[a][0]-cad.points[b][0]):[]
 const selected=row[channel],start=cad?cad.points[selected]:[(palm?455:475)+channel*36.2,palm?336:373],end=cad?cad.points[selected+32]:[start[0],palm?530:180]
 const drawing=<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${palm?'Palm to dorsal':'Dorsal to palmar'} group, channel ${channel+1} of 16`}>
  <image href={cad?`./assembly/renders/${key}.webp`:'./assembly/media/panel-079-2.png'} width={width} height={height}/>
  {cad&&<><text x={width/2} y={height*.18} textAnchor="middle" fontSize="34" fill="currentColor">Palm · palmar</text><text x={width/2} y={height*.88} textAnchor="middle" fontSize="34" fill="currentColor">Dorsum · dorsal</text></>}
  {cad&&row.map(i=><circle key={i} cx={cad.points[i][0]} cy={cad.points[i][1]} r="9" fill={color} opacity=".6"/>)}
  <path d={`M${start} L${end}`} stroke="#fff" strokeWidth="13"/>
  <path d={`M${start} L${end}`} stroke={color} strokeWidth="7"/>
  <path d={`M${end[0]-10},${end[1]+(palm?-15:15)} L${end} L${end[0]+10},${end[1]+(palm?-15:15)}`} stroke={color} strokeWidth="7" fill="none"/>
  <circle cx={start[0]} cy={start[1]} r="19" fill="none" stroke={color} strokeWidth="5"/>
  <text x={end[0]} y={end[1]+(palm?44:-28)} textAnchor="middle" fontSize="30" fontWeight="bold" fill={color}>{channel+1}</text>
 </svg>
 return <section className="assembly-wrist-routing"><h3>Two groups · keep the order within each</h3><p>Look at the underside of the carpals, with the palm above and dorsum below as shown. Send the palm-side row toward the dorsal side of the wrist, and the dorsal row toward the palmar side. Within each group, work from left to right without crossing the strands.</p>
  <div className="assembly-clip-tabs"><button aria-pressed={palm} onClick={()=>{setPalm(true);setChannel(0)}}>Palm tendons → dorsal wrist</button><button aria-pressed={!palm} onClick={()=>{setPalm(false);setChannel(0)}}>Dorsal tendons → palmar wrist</button></div>
  <button className="assembly-image-button" aria-label="Enlarge carpal routing" onClick={()=>dialog.current?.showModal()}>{drawing}</button>
  <dialog ref={dialog} className="assembly-lightbox assembly-route-dialog" aria-label="Carpal routing" onCancel={e=>e.stopPropagation()} onClick={e=>{if(e.target===e.currentTarget)dialog.current?.close()}}><div className="assembly-row"><span>Carpal underside · {channel+1} / 16</span><button autoFocus onClick={()=>dialog.current?.close()}>Close routing ×</button></div>{drawing}</dialog>
  <div className="assembly-row"><button className="assembly-secondary" disabled={channel===0} onClick={()=>setChannel(channel-1)}>← Previous channel</button><span>{channel+1} / 16 · {palm?'palm':'dorsal'} group</span><button className="assembly-secondary" disabled={channel===15} onClick={()=>setChannel(channel+1)}>Next channel →</button></div>
  <p>The arrow shows the receiving wrist side, not the final curve of the tendon. Numbers count positions within this row. Verify individual tendon names in “Verify all 32 tendon identities” after threading both groups.</p>
 </section>
}

import {photoResolution} from './photoResolution'
import {useRef,useState} from 'react'
import type {Build} from './buildContent'
const phases=[
 {title:'Choose the order',text:'Open Flashing in ORCA Console. Select the order matching this hand and check its identity.',images:['105-1']},
 {title:'Connect Bench Helper',text:'If the helper is not reachable, open Bench setup and start it on the assembly computer. Continue when it says connected.',images:['106-1','106-2']},
 {title:'Start the flash',text:'Press Flash. Show instructions explains the connection sequence; Show output displays progress.',images:['107-1']},
 {title:'Hold the probe',text:'Connect J-Link and hold the Tag-Connect firmly against the board’s flashing pads while the bootloader is written.',images:['108-1','108-2']},
 {title:'Lift the probe',text:'When prompted, remove the Tag-Connect from the pads. Leave board power and USB-C connected for the firmware and identity stages.',images:['108-4']},
 {title:'Confirm success',text:'Wait for the flashed-and-linked confirmation. If the process fails, inspect the output and connections before retrying.',images:['109-1']},
]
const imageNames:Record<string,string>={
 '105-1':'Flashing page · select the order for this hand',
 '106-1':'Not ready · Bench Helper is unreachable',
 '106-2':'Ready · Bench Helper is connected',
 '107-1':'Selected order, Flash button and output controls',
 '108-1':'OH board power, USB and programming connections',
 '108-2':'Hold the Tag-Connect on the programming pads',
 '108-4':'Prompt to lift the Tag-Connect off the pads',
 '109-1':'Success · flashed and linked',
}
export function FlashingWalkthrough({build}:{build:Build}){
 const [index,setIndex]=useState(0),[enlarged,setEnlarged]=useState(''),dialog=useRef<HTMLDialogElement>(null),phase=phases[index]
 return <section className="assembly-flashing-walkthrough" aria-label="ORCA Console flashing sequence">
  <div className="assembly-clip-tabs">{phases.map((p,i)=><button key={p.title} aria-pressed={i===index} onClick={()=>setIndex(i)}>{i+1} · {p.title}</button>)}</div>
  <h3>{phase.title}</h3><p>{phase.text}</p>
  {index!==3&&<p className="assembly-muted">The screenshots show an example order. Select the order for your {build.side} {build.version==='base'?'Base':build.version==='touch'?'Touch':'Full'} hand with {build.motor==='dynamixel'?'Dynamixel':'FeeTech'} motors.</p>}
  <div className={`assembly-flash-images ${index===3?'is-photos':'is-screens'}`}>{phase.images.map(id=><figure key={id}><button className="assembly-image-button" aria-label={`Enlarge ${imageNames[id]}`} onClick={()=>{setEnlarged(photoResolution(`./assembly/media/panel-${id}.png`));dialog.current?.showModal()}}><img src={photoResolution(`./assembly/media/panel-${id}.png`)} alt={imageNames[id]}/></button><figcaption>{imageNames[id]}</figcaption></figure>)}</div>
  <div className="assembly-row"><button className="assembly-secondary" disabled={index===0} onClick={()=>setIndex(i=>i-1)}>← Previous</button><span>{index+1} / {phases.length}</span><button className="assembly-primary" disabled={index===phases.length-1} onClick={()=>setIndex(i=>i+1)}>Next →</button></div>
 <dialog ref={dialog} className="assembly-lightbox" aria-label="Flashing detail" onCancel={e=>e.stopPropagation()}><button onClick={()=>dialog.current?.close()}>Close image ×</button>{enlarged&&<img src={enlarged} alt={phase.title}/>}</dialog>
 </section>
}

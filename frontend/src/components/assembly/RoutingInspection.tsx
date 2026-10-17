import {useState} from 'react'
import {PartAssemblyMotion} from './PartAssemblyMotion'
import {AssemblyComparison} from './AssemblyComparison'
import type {Build} from './buildContent'

const AREAS=[
 {step:'p42',label:'Finger AP',photos:[1,2,3,4].map(i=>`panel-081-${i}.png`),text:'Follow the four DP/PP strands through the AP, plus its two anchor ends. Check each finger separately; this view shows the index finger.'},
 {step:'p62',label:'Thumb TP',photos:[5,6].map(i=>`panel-081-${i}.png`),text:'Follow all six passing strands between the TP guide pins. Keep the two TP anchor ends separate: eight ends leave the finished thumb.'},
 {step:'p89',label:'Carpals → wrist',photos:[1,2].map(i=>`panel-082-${i}.png`),text:'Trace each strand from its carpal outlet to its wrist channel. Each group keeps its order; check for a hidden second crossing as well as a single swap.'},
] as const

export function RoutingInspection({build}:{build:Build}){
 const [selected,setSelected]=useState(0),[transparent,setTransparent]=useState(true),area=AREAS[selected]
 const model=()=> <div data-contrast={build.version!=='touch'||area.step==='p89'}><PartAssemblyMotion key={area.step} build={build} step={area.step} position={1} tendon={-1} channels={transparent} zoom={1.35}/></div>
 return <section className="assembly-routing-inspection" aria-label="Inspect tendon routing">
  <div className="assembly-row"><h3>Trace each strand</h3><AssemblyComparison key={area.step} step="p80" build={build} model={model} photoSources={area.photos}/></div>
  <div className="assembly-clip-tabs">{AREAS.map((item,i)=><button key={item.step} aria-pressed={selected===i} onClick={()=>setSelected(i)}>{item.label}</button>)}</div>
  <p>{area.text}</p>
  <label className="assembly-route-check"><input type="checkbox" checked={transparent} onChange={e=>setTransparent(e.target.checked)}/> See through the parts</label>
  {model()}
  <p className="assembly-muted">Drag to inspect from another angle; scroll or pinch to zoom. Strands can overlap in a flat view without touching: rotate the model and trace each one. Open the assembly photos to compare actual correct and crossed examples.</p>
  {selected===2&&build.motor==='feetech'&&<p className="assembly-muted">The wrist reference shows the Dynamixel frame.</p>}
  <div className="assembly-crossing-examples" aria-label="Tendon crossing examples">{['Clear path','Single crossing','Double crossing'].map((title,i)=><figure key={title}>
   <svg viewBox="0 0 240 170" role="img" aria-label={title}>
    <g fill="none" strokeLinecap="round" strokeWidth="6">
     <path d={i===0?'M85 15 V155':i===1?'M85 15 C85 70 155 100 155 155':'M85 15 C85 50 155 40 155 85 S85 110 85 155'} stroke="#24533f"/>
     <path d={i===0?'M155 15 V155':i===1?'M155 15 C155 70 85 100 85 155':'M155 15 C155 50 85 40 85 85 S155 110 155 155'} stroke="var(--assembly-image-bg)" strokeWidth="12"/>
     <path d={i===0?'M155 15 V155':i===1?'M155 15 C155 70 85 100 85 155':'M155 15 C155 50 85 40 85 85 S155 110 155 155'} stroke="#fff"/>
    </g>
   </svg><figcaption><strong>{title}</strong><span>{i===0?'Neighboring strands stay separate.':i===1?'The strands swap positions.':'They cross twice, even though the ends return to the same order.'}</span></figcaption>
  </figure>)}</div>
 </section>
}

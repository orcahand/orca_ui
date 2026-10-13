import { JointLesson } from './JointLesson'
import { HandModel } from './HandModel'
import { useState } from 'react'
import type { Build } from './buildContent'

const TERMS = [
  ['DP', 'Distal part', 'The outer finger segment, nearest the fingertip.'],
  ['PP', 'Proximal part', 'The segment behind DP, toward the hand.'],
  ['AP', 'Finger base', 'The base part that allows the finger to move sideways.'],
  ['TP', 'Thumb base', 'The extra thumb part between AP and the hand body. Only the thumb has a TP.'],
  ['Carpals', 'Hand body', 'The structure where all five fingers attach. The palm skin fits on its palmar face.'],
  ['Wrist', 'Wrist assembly', 'The structure and drive between the carpals and the motor tower.'],
  ['Tower', 'Motor tower', 'The lower structure holding the spool motors, electronics and hull covers.'],
]
export function HandLabels({build}:{build:Build}) {
  const [selected,setSelected]=useState('DP')
  const [face,setFace]=useState<'palmar'|'dorsal'>('palmar')
  const term=TERMS.find(t=>t[0]===selected)!
  return <section className="assembly-anatomy">
    <div className="assembly-row"><p>{build.version==='touch'?'Touch':'Base'} {build.side} hand anatomy. Select a label; the other parts fade away. Drag to inspect.</p><div className="assembly-clip-tabs">{(['palmar','dorsal'] as const).map(side=><button key={side} aria-pressed={face===side} onClick={()=>setFace(side)}>{side==='palmar'?'Palmar · palm':'Dorsal · back'}</button>)}</div></div>
    <div className="assembly-anatomy-map">
      <HandModel build={build} selected={selected} face={face}/>
      <div><div className="assembly-anatomy-labels">{TERMS.map(([id])=><button key={id} aria-pressed={selected===id} onClick={()=>setSelected(id)}>{id}</button>)}</div><div className="assembly-anatomy-definition" aria-live="polite"><span className="assembly-eyebrow">{term[1]}</span><h3>{term[0]}</h3><p>{term[2]}</p></div><p className="assembly-muted">{face==='palmar'?'Palmar means the palm-facing side—the inner face of the hand.':'Dorsal means the back of the hand, opposite the palm.'}<br/>Proximal = toward the hand / wrist.</p></div>
    </div>
    <JointLesson build={build}/>

  </section>
}

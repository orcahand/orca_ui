import { JointLesson } from './JointLesson'
import { HandModel } from './HandModel'
import { useState } from 'react'
import type { Build } from './buildContent'

const TERMS = [
  ['DP', 'Distal phalanx', 'The outer finger segment, nearest the fingertip.'],
  ['PP', 'Proximal phalanx', 'The segment behind DP, toward the hand.'],
  ['AP', 'Abduction phalanx', 'The base phalanx that allows the finger to move sideways.'],
  ['TP', 'Thumb phalanx', 'The extra thumb phalanx between AP and the hand body. Only the thumb has a TP.'],
  ['Carpals', 'Hand body', 'The structure where all five fingers attach. The palm skin fits on its palmar face.'],
  ['Wrist', 'Wrist assembly', 'The structure and drive between the carpals and the motor tower.'],
  ['Tower', 'Motor tower', 'The lower structure holding the spool motors, electronics and hull covers.'],
]
export function HandLabels({build}:{build:Build}) {
  const [selected,setSelected]=useState('DP')
  const [face,setFace]=useState<'palmar'|'dorsal'>('palmar')
  const term=TERMS.find(t=>t[0]===selected)!
  return <section className="assembly-anatomy">
    <div className="assembly-anatomy-map">
      <div className="assembly-anatomy-viewport"><div className="assembly-anatomy-face-tabs assembly-clip-tabs">{(['palmar','dorsal'] as const).map(side=><button key={side} aria-pressed={face===side} onClick={()=>setFace(side)}>{side==='palmar'?'Palmar · palm':'Dorsal · back'}</button>)}</div><HandModel build={build} selected={selected} face={face}/></div>
      <div><div className="assembly-anatomy-labels">{TERMS.map(([id])=><button key={id} aria-pressed={selected===id} onClick={()=>setSelected(id)}>{id}</button>)}</div><div className="assembly-anatomy-definition" aria-live="polite"><span className="assembly-eyebrow">{term[1]}</span><h3>{term[0]}</h3><p>{term[2]}</p></div><dl className="assembly-orientation-key"><div><dt>Distal</dt><dd>Toward the fingertip.</dd></div><div><dt>Proximal</dt><dd>Toward the hand and wrist.</dd></div><div><dt>Palmar</dt><dd>The palm-facing surface.</dd></div><div><dt>Dorsal</dt><dd>The back of the hand, opposite the palm.</dd></div></dl></div>
    </div>
    <JointLesson build={build}/>

  </section>
}

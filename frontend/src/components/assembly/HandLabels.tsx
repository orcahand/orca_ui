import {GuideText} from './GuideEditing'
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
  const [selected,setSelected]=useState('')
  const [face,setFace]=useState<'palmar'|'dorsal'>('palmar')
  const [mode,setMode]=useState<'parts'|'movement'>('parts')
  const term=TERMS.find(t=>t[0]===selected)
  return <section className="assembly-anatomy" data-contrast={build.version!=='touch'}>
    <div className="assembly-clip-tabs" role="tablist" aria-label="Hand reference" onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const next=e.key==='Home'?'parts':e.key==='End'?'movement':mode==='parts'?'movement':'parts';setMode(next);document.getElementById(`anatomy-${next}-tab`)?.focus()}}><button role="tab" tabIndex={mode==='parts'?0:-1} id="anatomy-parts-tab" aria-controls="anatomy-parts" aria-selected={mode==='parts'} onClick={()=>setMode('parts')}>Parts</button><button role="tab" tabIndex={mode==='movement'?0:-1} id="anatomy-movement-tab" aria-controls="anatomy-movement" aria-selected={mode==='movement'} onClick={()=>setMode('movement')}>Movement</button></div>
    {mode==='parts'?<div role="tabpanel" id="anatomy-parts" aria-labelledby="anatomy-parts-tab" className="assembly-anatomy-map">
      <div className="assembly-anatomy-viewport"><HandModel build={build} selected={selected} face={face}/></div>
      <div><div className="assembly-anatomy-face-tabs assembly-clip-tabs">{(['palmar','dorsal'] as const).map(side=><button key={side} aria-pressed={face===side} onClick={()=>setFace(side)}>{side==='palmar'?'Palmar · palm':'Dorsal · back'}</button>)}</div><div className="assembly-anatomy-labels"><button aria-pressed={!selected} onClick={()=>setSelected('')}>Whole hand</button>{TERMS.map(([id])=><button key={id} aria-pressed={selected===id} onClick={()=>setSelected(selected===id?'':id)}>{id}</button>)}</div>{term&&<div className="assembly-anatomy-definition" aria-live="polite"><span className="assembly-eyebrow">{term[1]}</span><h3><GuideText variant field="prose/HandLabels.tsx/5e479087dc" text={String(term[0])} label="Section heading"/></h3><p><GuideText variant field="prose/HandLabels.tsx/e1c8973938" text={String(term[2])} label="Guide text"/></p></div>}<dl className="assembly-orientation-key"><div><dt><GuideText variant field="prose/HandLabels.tsx/5717a97fa3" text={"Distal"} label="Guide text"/></dt><dd><GuideText variant field="prose/HandLabels.tsx/0e5f34de1a" text={"Toward the fingertip."} label="Guide text"/></dd></div><div><dt><GuideText variant field="prose/HandLabels.tsx/d01a965609" text={"Proximal"} label="Guide text"/></dt><dd><GuideText variant field="prose/HandLabels.tsx/2a334373ba" text={"Toward the hand and wrist."} label="Guide text"/></dd></div><div><dt><GuideText variant field="prose/HandLabels.tsx/c550404d8d" text={"Palmar"} label="Guide text"/></dt><dd><GuideText variant field="prose/HandLabels.tsx/ff80f6cbe7" text={"The palm-facing surface."} label="Guide text"/></dd></div><div><dt><GuideText variant field="prose/HandLabels.tsx/0c50d853eb" text={"Dorsal"} label="Guide text"/></dt><dd><GuideText variant field="prose/HandLabels.tsx/56e41d6d49" text={"The back of the hand, opposite the palm."} label="Guide text"/></dd></div></dl></div>
    </div>:<div role="tabpanel" id="anatomy-movement" aria-labelledby="anatomy-movement-tab"><JointLesson build={build}/></div>}

  </section>
}

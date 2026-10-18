import {GuideText} from './GuideEditing'
import {photoResolution} from './photoResolution'
import { useEffect, useState } from 'react'
import type { Build } from './buildContent'
import { FINGERS, MOVEMENTS } from './fingerMovements'
import views from './cad-route-views.json'
import {FingerOutlets} from './FingerOutlets'
import {CadFingerMovement} from './CadFingerMovement'
export function FingerMotion({build,indexOnly=false,wholeIndex=false}:{build:Build;indexOnly?:boolean;wholeIndex?:boolean}) {
  const [finger,setFinger]=useState('index'),[movement,setMovement]=useState(0),[playing,setPlaying]=useState(false),[replay,setReplay]=useState(0)
  useEffect(()=>{if(!playing)return;const timer=setTimeout(()=>setPlaying(false),3100);return()=>clearTimeout(timer)},[playing,replay])
  const referenceKey=`${build.version}-${build.side}-dynamixel/route-p35-pair`
  const reference=(views as Record<string,{width:number;height:number;points:number[][]}>)[referenceKey]
  const point=reference?.points[movement+2]??[0,0]
  function play(){setReplay(n=>n+1);setPlaying(true)}
  return <section className="assembly-finger-movements"><h3><GuideText variant field="prose/FingerMotion.tsx/5c6c9db32c" text={String(indexOnly?'Check DP flexion and extension':wholeIndex?'Check all six index-finger tendons':'Check all six tendons on each finger')} label="Section heading"/></h3><p><GuideText variant field="prose/FingerMotion.tsx/1baca89b49" text={"Support the finger at its base. Gently pull one free end and leave the others slack. Select a tendon to see the expected movement."} label="Guide text"/></p>
    {!indexOnly&&!wholeIndex&&<div className="assembly-clip-tabs">{FINGERS.map(f=><button key={f} aria-pressed={finger===f.toLowerCase()} onClick={()=>{setFinger(f.toLowerCase());play()}}>{f}</button>)}</div>}
    <div className="assembly-clip-tabs">{MOVEMENTS.slice(0,indexOnly?2:6).map(([name],i)=><button key={name} aria-pressed={movement===i} onClick={()=>{setMovement(i);play()}}>{name}</button>)}</div>
    <div className={`assembly-movement-views has-pair-reference`}><div className="assembly-finger-preview" aria-label={`${finger} ${MOVEMENTS[movement][0]} demonstration`}><CadFingerMovement build={build} finger={finger} movement={movement} playing={playing} replay={replay} isolated={indexOnly}/></div>{indexOnly&&<figure className="assembly-dp-reference"><figcaption><GuideText variant field="prose/FingerMotion.tsx/dc4cd6efa1" text={"Identify the two ends leaving the PP"} label="Guide text"/></figcaption>{reference?<svg viewBox={`0 0 ${reference.width} ${reference.height}`} role="img" aria-label={`${MOVEMENTS[movement][0]} end leaving the PP`}><image href={`./assembly/renders/${referenceKey}.webp`} width={reference.width} height={reference.height}/><circle cx={point[0]} cy={point[1]} r="28" fill="none" stroke={movement===0?'#d7b83f':'#aa83dd'} strokeWidth="9"/></svg>:<svg viewBox="0 0 475 318" role="img" aria-label={`${MOVEMENTS[movement][0]} tendon highlighted on the assembled PP`}><image href={photoResolution('./assembly/media/panel-036-3.png')} width="475" height="318"/><path d={movement===0?'M143 217 Q90 244 23 277':'M143 223 Q100 245 38 299'} stroke={movement===0?'#ffe16b':'#c5a2ff'} strokeWidth="5" fill="none"/><path className={playing?'assembly-route-flow':''} d={movement===0?'M143 217 Q90 244 23 277':'M143 223 Q100 245 38 299'} stroke="white" strokeWidth="2" strokeDasharray="6 15" fill="none"/><circle cx="143" cy={movement===0?217:223} r="10" fill="none" stroke={movement===0?'#ffe16b':'#c5a2ff'} strokeWidth="2"/></svg>}<p><GuideText variant field="prose/FingerMotion.tsx/ecb9d3c36f" text={String(movement===0?'Yellow · DP flex · fingertip bends toward palm.':'Purple · DP ext · fingertip straightens away from palm.')} label="Guide text"/></p></figure>}{!indexOnly&&<FingerOutlets build={build} finger={finger} movement={movement}/>}</div>

    <div className="assembly-pull-key" aria-live="polite"><span style={{background:['#d7b83f','#aa83dd','#e68f50','#56b8c5','#8ab454','#cb728a'][movement]}}/><strong>Pull {MOVEMENTS[movement][0]}</strong><span>Leave {indexOnly?MOVEMENTS[1-movement][0]:'the other five ends'} slack. Watch the selected joint; the other joints stay free.</span></div>

    <p><GuideText variant field="prose/FingerMotion.tsx/3a0b8b054a" text={"If another joint moves, trace that tendon back through its routing. If it binds, check for trapped strands and unseated bearings before pulling again."} label="Guide text"/></p>
  </section>
}

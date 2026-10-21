import {useEffect,useState} from 'react'
export function InstructionSequence({instructions,index,onSelect}:{instructions:string[];index:number;onSelect:(index:number)=>void}){
 const [playing,setPlaying]=useState(false)
 useEffect(()=>{
  if(!playing)return
  const timer=setTimeout(()=>{if(index>=instructions.length-1)setPlaying(false);else onSelect(index+1)},Math.max(5000,(instructions[Math.max(0,index)]?.split(' ').length??20)*220))
  return()=>clearTimeout(timer)
 },[playing,index,instructions,onSelect])
 if(instructions.length<2)return null
 return <div className="assembly-instruction-sequence" aria-label="Instruction controls">
  <span aria-live="polite">{index<0?'All instructions':`${index+1} / ${instructions.length}`}</span>
  <button className="assembly-text-button" onClick={()=>{setPlaying(false);onSelect(index<0?0:-1)}}>{index<0?'One at a time':'Show all'}</button>
  <button className="assembly-text-button" aria-label="Previous instruction" disabled={index<=0} onClick={()=>{setPlaying(false);onSelect(index-1)}}>←</button>
  <button className="assembly-text-button" aria-label="Next instruction" disabled={index>=instructions.length-1} onClick={()=>{setPlaying(false);onSelect(index+1)}}>→</button>
  <button className="assembly-secondary assembly-walkthrough-play" aria-label={playing?'Pause walkthrough':'Play walkthrough'} aria-pressed={playing} onClick={()=>{if(index<0||index>=instructions.length-1)onSelect(0);setPlaying(!playing)}}>{playing?'Ⅱ':'▶'}</button>
 </div>
}

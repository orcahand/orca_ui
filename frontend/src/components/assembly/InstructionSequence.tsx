import {useEffect,useState} from 'react'
export function InstructionSequence({instructions,index,onSelect}:{instructions:string[];index:number;onSelect:(index:number)=>void}){
 const [playing,setPlaying]=useState(false)
 useEffect(()=>{
  if(!playing)return
  const timer=setTimeout(()=>{if(index>=instructions.length-1)setPlaying(false);else onSelect(index+1)},Math.max(5000,(instructions[Math.max(0,index)]?.split(' ').length??20)*220))
  return()=>clearTimeout(timer)
 },[playing,index,instructions,onSelect])
 if(instructions.length<2)return null
 return <div className="assembly-instruction-sequence" aria-label="Walk through this step">
  <span>{index<0?'Walk through this step':`Instruction ${index+1} of ${instructions.length}`}</span>
  <button className="assembly-text-button" disabled={index<=0} onClick={()=>{setPlaying(false);onSelect(index-1)}}>← Back</button>
  <button className="assembly-secondary" onClick={()=>{if(index<0||index>=instructions.length-1)onSelect(0);setPlaying(!playing)}}>{playing?'Pause walkthrough':'Play walkthrough'}</button>
  <button className="assembly-text-button" disabled={index>=instructions.length-1} onClick={()=>{setPlaying(false);onSelect(index+1)}}>Next →</button>
  {index>=0&&<button className="assembly-text-button" onClick={()=>{setPlaying(false);onSelect(-1)}}>Show all</button>}
 </div>
}

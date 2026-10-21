import { useEffect, useRef, useState } from 'react'
import { PROGRESS_KEY, readProgress, validateProgress, type Progress } from './progress'

// Serialize writes across popup mounts so an older save cannot finish last.
let writes = Promise.resolve()
function persist(progress: Progress) {
  const payload = JSON.stringify(progress)
  const request = writes.catch(()=>{}).then(async()=>{
    const response=await fetch('/api/assembly/progress',{method:'PUT',headers:{'Content-Type':'application/json'},body:payload,keepalive:true,signal:AbortSignal.timeout(5000)})
    if(!response.ok) throw new Error('Save failed')
  })
  writes=request
  return request
}
export function useAssemblyProgress() {
  const [progress,setProgress]=useState(readProgress)
  const [ready,setReady]=useState(false)
  const [serverAvailable,setServerAvailable]=useState(false)
  const [saveStatus,setSaveStatus]=useState('Loading saved progress…')
  const generation=useRef(0)
  useEffect(()=>{
    let active=true
    // Flush a previous popup's last save before restoring its state.
    writes.catch(()=>{}).then(()=>fetch('/api/assembly/progress',{signal:AbortSignal.timeout(4000)})).then(async response=>{
      if(!response.ok) throw new Error('Load failed')
      const value=await response.json()
      if(active) {setServerAvailable(true);if(value) setProgress(validateProgress(value))}
    }).catch(()=>{if(active)setSaveStatus('Saved in this browser; server saving is unavailable.')}).finally(()=>{if(active)setReady(true)})
    return ()=>{active=false}
  },[])
  useEffect(()=>{
    if(!ready) return
    const revision=++generation.current
    let local=true
    try {localStorage.setItem(PROGRESS_KEY,JSON.stringify(progress))} catch {local=false}
    if(!serverAvailable) {setSaveStatus(local ? 'Saved in this browser; server saving is unavailable.' : 'Saving is unavailable. Keep the guide open to retain your progress.');return}
    setSaveStatus('Saving your place…')
    persist(progress).then(()=>{if(generation.current===revision)setSaveStatus('Your place is saved automatically.')}).catch(()=>{
      if(generation.current===revision)setSaveStatus(local ? 'Saved in this browser; server saving is unavailable.' : 'Saving is unavailable. Keep the guide open to retain your progress.')
    })
  },[progress,ready,serverAvailable])
  return {progress,setProgress,ready,saveStatus}
}

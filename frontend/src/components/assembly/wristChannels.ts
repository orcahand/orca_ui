import outlets from './wristOutlets.json'
// Numbered outlet centers traced from the right/left wrist diagrams.
export function wristChannel(side:'left'|'right',index:number):[number,number]{
 const right=[...Array.from({length:4},(_,i)=>[114+i*23,217]),...Array.from({length:4},(_,i)=>[335+i*22.5,184]),...Array.from({length:4},(_,i)=>[335+i*22.5,217]),...Array.from({length:4},(_,i)=>[556+i*22.5,184]),...Array.from({length:4},(_,i)=>[624-i*22.5,647]),...Array.from({length:4},(_,i)=>[402-i*22.5,680]),...Array.from({length:4},(_,i)=>[402-i*22.5,647]),...Array.from({length:4},(_,i)=>[182-i*23,680])]
 const left=[...Array.from({length:4},(_,i)=>[607-i*22.5,172]),...Array.from({length:4},(_,i)=>[385-i*23,205]),...Array.from({length:4},(_,i)=>[385-i*23,172]),...Array.from({length:4},(_,i)=>[161-i*22.5,205]),...Array.from({length:4},(_,i)=>[94+i*22.5,672]),...Array.from({length:4},(_,i)=>[316+i*23,638]),...Array.from({length:4},(_,i)=>[316+i*23,672]),...Array.from({length:4},(_,i)=>[540+i*22.5,638])]
 return (side==='left'?left:right)[index] as [number,number]
}

export function wristOutlet(side:'left'|'right',index:number):[number,number,number]{
 const [_,py]=wristChannel(side,index),outer=side==='right'?[184,680].includes(py):[172,672].includes(py),palmar=py<400
 const row=outlets.filter(p=>(p[2]<0)===palmar&&(Math.abs(p[2])>35)===outer).sort((a,b)=>b[0]-a[0])
 const numbers=Array.from({length:32},(_,i)=>i).filter(i=>wristChannel(side,i)[1]===py).sort((a,b)=>wristChannel(side,a)[0]-wristChannel(side,b)[0])
 return row[numbers.indexOf(index)] as [number,number,number]
}

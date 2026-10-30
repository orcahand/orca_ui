import {useEffect,useMemo,useState} from 'react'
import {Canvas} from '@react-three/fiber'
import {OrbitControls} from '@react-three/drei'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces,framed,nearest} from './cadScene'
import {anchorStopper} from './anchorStopper'
import type {Build} from './buildContent'

function FingerKit({bundle,build,finger,amount}:{bundle:Bundle;build:Build;finger:string;amount:number}){
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),group=new THREE.Group()
  const bodies=pieces.filter(p=>/^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label))
  const names=['DP','PP','AP'].map(part=>`${finger} ${part}`)
  const selected=pieces.filter(p=>names.includes(p.part.label)||['Skins','Standard components'].includes(p.part.category)&&names.includes(p.owner??nearest(bodies,p.center)?.part.label??''))
  const bounds=new THREE.Box3();selected.forEach(p=>bounds.union(p.bounds));const center=bounds.getCenter(new THREE.Vector3())
  const offsets=selected.map(p=>{const segment=names.indexOf(p.owner??p.part.label.replace(' skin',''));const shift=new THREE.Vector3(0,(1-Math.max(0,segment))*24,0)
   if(p.part.category==='Standard components')shift.add(p.axis.clone().multiplyScalar(p.center.x<center.x?-18:18))
   else if(p.part.category==='Skins')shift.add(new THREE.Vector3(28,0,0))
   p.object.position.copy(shift);group.add(p.object);return shift
  })
  const cords=new THREE.Group(),extras:{dispose:()=>void}[]=[]
  for(let i=0;i<4;i++){
   const points=Array.from({length:241},(_,n)=>{const t=n/240*Math.PI*4;return new THREE.Vector3(Math.cos(t)*10,Math.sin(t)*10,t*.24)})
   const geometry=new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),240,.3,8,false),material=new THREE.MeshStandardMaterial({color:i<2?'#408f97':'#d8ad53'})
   const cord=new THREE.Group();cord.add(new THREE.Mesh(geometry,material));cord.position.copy(center).add(new THREE.Vector3(50+(i%2)*28,35-Math.floor(i/2)*45,0));cord.rotation.y=.4;cords.add(cord)
   extras.push({dispose:()=>{geometry.dispose();material.dispose()}})
   if(i<2)for(const x of [-5,5]){const knot=anchorStopper(.6,1);knot.group.position.set(x,-10,2);cord.add(knot.group);extras.push(knot)}
  }
  group.add(cords);const view=framed(group,build,350,600)
  return {view,update:(t:number)=>{selected.forEach((p,i)=>p.object.position.copy(offsets[i]).multiplyScalar(t));cords.visible=t>.05;cords.scale.setScalar(Math.max(.001,t))},dispose:()=>{disposePieces(pieces);extras.forEach(x=>x.dispose())}}
 },[bundle,build,finger])
 useEffect(()=>{scene.update(amount)},[scene,amount]);useEffect(()=>()=>scene.dispose(),[scene])
 return <primitive object={scene.view}/>
}
export function FingerPreparation({build,otherFingers=false}:{build:Build;otherFingers?:boolean}){
 const [finger,setFinger]=useState(otherFingers?'Middle':'Index'),[amount,setAmount]=useState(1),[bundle,setBundle]=useState<Bundle|null>(null),[error,setError]=useState(false)
 const key=`base-${build.side}-dynamixel`
 useEffect(()=>{let live=true;setBundle(null);setError(false);loadBundle(key).then(b=>{if(live)setBundle(b)}).catch(()=>{if(live)setError(true)});return()=>{live=false}},[key])
 return <section className="assembly-finger-preparation" aria-label="Exploded finger parts and tendon stock">
  {otherFingers&&<label>Finger to assemble <select aria-label="Finger to assemble" value={finger} onChange={e=>setFinger(e.target.value)}>{['Middle','Ring','Pinky'].map(f=><option key={f}>{f}</option>)}</select></label>}
  <div className="assembly-cad-detail-canvas">{bundle?<Canvas orthographic camera={{position:[0,0,1000],near:.1,far:4000}} dpr={[1,2]}><ambientLight intensity={1.4}/><directionalLight position={[250,400,600]} intensity={3}/><directionalLight position={[-300,0,-500]} intensity={2}/><FingerKit bundle={bundle} build={build} finger={finger} amount={amount}/><OrbitControls enablePan minZoom={.5} maxZoom={3}/></Canvas>:<p>{error?'Unable to load the finger parts. Reopen this step to retry.':'Loading finger parts…'}</p>}</div>
  <label className="assembly-motion-scrubber"><span>Assembled</span><input type="range" aria-label="Explode finger parts" min="0" max="100" value={amount*100} onChange={e=>setAmount(+e.target.value/100)}/><span>Exploded</span></label>
  <p>DP, PP and AP · matching skins · 6 bearings · 3 Ø2×8 mm pins · 2 Ø2×6 mm pins.</p>
  <p><span style={{color:'#408f97'}}>Teal: 2 prepared tendons × 2 m</span>, each with two Ashley stoppers and one single knot over each stopper. <span style={{color:'#9a742b'}}>Gold: 2 unknotted AP tendons × 75 cm</span>. Coils show the stock separately; lengths are not to scale.</p>
 </section>
}

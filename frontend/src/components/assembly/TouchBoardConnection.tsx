import {GuideText} from './GuideEditing'
import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react'
import {Canvas,useThree} from '@react-three/fiber'
import {Html,OrbitControls} from '@react-three/drei'
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js'
import * as THREE from 'three'
import {loadBundle,type Bundle} from './cadAssets'
import {cadPieces,disposePieces} from './cadScene'
import type {Build} from './buildContent'

const TOUCH_PORT=new THREE.Vector3(-14.98,124.42,13.3)
const OH_PORT=new THREE.Vector3(-25.6,32,50.3)
function BoardDiagram({bundle,board,build,selected}:{bundle:Bundle;board:THREE.Group;build:Build;selected:number}){
 const wrapper=useRef<THREE.Group>(null),{size,invalidate,camera}=useThree()
 const scene=useMemo(()=>{
  const pieces=cadPieces(bundle,build),oh=pieces.find(p=>p.part.label==='OH control board')!,group=new THREE.Group()
  // Both connector faces use the verified right-hand board reference, independent of hand side.
  group.add(oh.object)
  const touch=board.clone(true)
  touch.traverse(n=>{if(n instanceof THREE.Mesh)n.material=new THREE.MeshStandardMaterial({color:'#ffffff',vertexColors:true,roughness:.7,metalness:0})})
  group.add(touch)
  const curve=new THREE.CatmullRomCurve3([TOUCH_PORT,new THREE.Vector3(-15,113,16),new THREE.Vector3(-45,100,26),new THREE.Vector3(-48,65,42),new THREE.Vector3(-26,45,50.3),OH_PORT])
  const cable=new THREE.Mesh(new THREE.TubeGeometry(curve,160,1.1,20,false),new THREE.MeshStandardMaterial({color:'#287f8d',roughness:.7}))
  group.add(cable)
  const box=new THREE.Box3().setFromObject(group),center=box.getCenter(new THREE.Vector3());group.position.copy(center).negate()
  return {group,pieces,touch,cable,center,box}
 },[bundle,board,build])
 useLayoutEffect(()=>{
  camera.position.set(0,selected===0?-500:selected===1?500:0,1000);camera.up.set(0,1,0);camera.lookAt(0,0,0);camera.updateProjectionMatrix()
  const scale=Math.min((size.width-100)/scene.box.getSize(new THREE.Vector3()).x,(size.height-55)/scene.box.getSize(new THREE.Vector3()).y)
  const zoom=selected<0?1:3.2;wrapper.current!.scale.setScalar(scale*zoom);wrapper.current!.position.copy(selected<0?new THREE.Vector3():(selected===0?TOUCH_PORT:OH_PORT).clone().sub(scene.center).multiplyScalar(-scale*zoom));invalidate()
 },[scene,size.width,size.height,selected,invalidate,camera])
 useEffect(()=>()=>{disposePieces(scene.pieces);scene.touch.traverse(n=>{if(n instanceof THREE.Mesh)(n.material as THREE.Material).dispose()});scene.cable.geometry.dispose();(scene.cable.material as THREE.Material).dispose()},[scene])
 return <group ref={wrapper}><primitive object={scene.group}>
  {[TOUCH_PORT,OH_PORT].map((p,i)=><group key={i} position={p}><mesh renderOrder={5}><sphereGeometry args={[selected===i?2.7:1.8,32,20]}/><meshBasicMaterial color={selected===i?'#087e91':'#dda64d'} transparent opacity={.65} depthTest={false}/></mesh><Html position={[i===0?14:-14,0,2]} center><span className="assembly-board-port-label">{i===0?'A':'B'}</span></Html></group>)}
 </primitive></group>
}
export function TouchBoardConnection(){
 const [loaded,setLoaded]=useState<{bundle:Bundle;board:THREE.Group}|null>(null),[failed,setFailed]=useState(false),[selected,setSelected]=useState(-1)
 const build=useMemo<Build>(()=>({version:'touch',side:'right',motor:'dynamixel',audience:'external'}),[])
 useEffect(()=>{let live=true;Promise.all([loadBundle('touch-right-dynamixel'),new GLTFLoader().loadAsync('./assembly/details/touch-connector-board.glb')]).then(([bundle,gltf])=>{if(live)setLoaded({bundle,board:gltf.scene})}).catch(()=>{if(live)setFailed(true)});return()=>{live=false}},[])
 return <section className="assembly-board-link" data-contrast={false} aria-label="Touch connector board to OH board cable">
  <span className="assembly-eyebrow">The link between the two boards</span><h3><GuideText variant field="prose/TouchBoardConnection.tsx/3cb708a195" text={"One cable, two four-pin sockets"} label="Section heading"/></h3>
  <div className="assembly-clip-tabs"><button aria-pressed={selected===-1} onClick={()=>setSelected(-1)}>Both boards</button><button aria-pressed={selected===0} onClick={()=>setSelected(0)}>A (Touch socket)</button><button aria-pressed={selected===1} onClick={()=>setSelected(1)}>B (OH socket)</button></div>
  <div className="assembly-board-link-layout"><div className="assembly-board-link-canvas">
   {loaded?<Canvas orthographic frameloop="demand" camera={{position:[0,0,1000],near:.1,far:3000}} dpr={[1,2]}><ambientLight intensity={1.8}/><directionalLight position={[-120,170,300]} intensity={3}/><BoardDiagram {...loaded} build={build} selected={selected}/><OrbitControls key={selected} enablePan={false} minZoom={.8} maxZoom={2.5}/></Canvas>:<p>{failed?'The connection diagram could not load. Reopen this step to retry.':'Loading the board connection…'}</p>}
  </div><div className="assembly-board-link-key">
   <button aria-pressed={selected===0} onClick={()=>setSelected(0)}><span>A</span><div><strong>Touch connector board</strong><p><GuideText variant field="prose/TouchBoardConnection.tsx/7f22c38bff" text={"Use the white four-pin socket below the five finger connectors. The finger cables use the smaller sockets around the board."} label="Guide text"/></p></div></button>
   <div className="assembly-board-cable-key"><i/><div><strong>Four-wire board cable</strong><p><GuideText variant field="prose/TouchBoardConnection.tsx/0e780ebc00" text={"Connect the prepared cable. Align each plug’s keyed housing with its socket and push on the plug housing."} label="Guide text"/></p></div></div>
   <button aria-pressed={selected===1} onClick={()=>setSelected(1)}><span>B</span><div><strong>OH control board</strong><p><GuideText variant field="prose/TouchBoardConnection.tsx/0362008087" text={"Use the four-pin connector-board socket labeled “Sensing”, next to the motor connectors. Match all four positions; the motor outputs have three."} label="Guide text"/></p></div></button>
   <p className="assembly-muted"><GuideText variant field="prose/TouchBoardConnection.tsx/44ab068853" text={"Boards shown outside the hand to make the connection clear. The colored cable marks the connection, not its installed shape or wire colors. Drag to inspect the keyed sockets."} label="Guide text"/></p>
  </div></div>
 </section>
}

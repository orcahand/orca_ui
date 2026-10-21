import * as THREE from 'three'

// Millimetres. Layout from wrap-short.png: 30 mm wrap, then 70 mm to
// the right connector. Connector shapes and cable diameter are illustrative.
export const TOUCH_CABLE={length:130,wrapStart:-35,wrapEnd:-5,pitch:1.2,wireRadius:.1,cableRadius:1.45}
export function touchCableScene(){
 const group=new THREE.Group(),geometries:THREE.BufferGeometry[]=[],materials:THREE.Material[]=[]
 const material=(color:string,metalness=0)=>{const m=new THREE.MeshStandardMaterial({color,roughness:metalness?.35:.85,metalness});materials.push(m);return m}
 const black=material('#25272a'),housing=material('#35383c'),copper=material('#cd8546',.65),metal=material('#d5d8dc',.7)
 const add=(geometry:THREE.BufferGeometry,m:THREE.Material,position:THREE.Vector3=new THREE.Vector3())=>{
  geometries.push(geometry);const mesh=new THREE.Mesh(geometry,m);mesh.position.copy(position);group.add(mesh);return mesh
 }
 const tube=(points:THREE.Vector3[],radius:number,m:THREE.Material,segments=160)=>add(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),segments,radius,10,false),m)
 const sleeve=add(new THREE.CylinderGeometry(TOUCH_CABLE.cableRadius,TOUCH_CABLE.cableRadius,116,32),black)
 sleeve.rotation.z=Math.PI/2
 // A subtle spiral seam conveys the black textile sleeve visible in the photo.
 const seam=material('#393b3e')
 tube(Array.from({length:800},(_,i)=>{const x=-58+116*i/799,a=x*Math.PI/3;return new THREE.Vector3(x,1.45*Math.cos(a),1.45*Math.sin(a))}),.045,seam,1000)
 const colors=['#c95546','#ebe3cf','#d3b849','#3f8a7b','#a7c5d4','#dc8353','#e3e6e3','#536777']
 for(const side of [-1,1]){
  add(new THREE.BoxGeometry(2,5,.9),housing,new THREE.Vector3(side*64,0,0))
  colors.forEach((color,i)=>{
   const y=(i-3.5)*.55
   tube([new THREE.Vector3(side*58,y*.22,0),new THREE.Vector3(side*60,y*.55,0),new THREE.Vector3(side*63,y,0)],.16,material(color),24)
   add(new THREE.BoxGeometry(.9,.28,.14),metal,new THREE.Vector3(side*64.6,y,.52))
  })
 }
 const {wrapStart,wrapEnd,pitch,wireRadius,cableRadius}=TOUCH_CABLE
 const turns=(wrapEnd-wrapStart)/pitch,radius=cableRadius+wireRadius
 const points=Array.from({length:2001},(_,i)=>{const t=i/2000,a=t*turns*Math.PI*2;return new THREE.Vector3(THREE.MathUtils.lerp(wrapStart,wrapEnd,t),radius*Math.cos(a),radius*Math.sin(a))})
 const wrap=tube(points,wireRadius,copper,2400);wrap.name='Copper wrap'
 const total=wrap.geometry.index!.count
 const update=(amount:number)=>wrap.geometry.setDrawRange(0,Math.floor(THREE.MathUtils.clamp(amount,0,1)*total/6)*6)
 return {group,wrap,update,dispose:()=>{geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose())}}
}

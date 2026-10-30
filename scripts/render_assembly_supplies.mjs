// Render the supplemental STL parts without adding them to the assembled hand.
// node scripts/render_assembly_supplies.mjs /path/to/playwright/tooling http://127.0.0.1:5187
import {createRequire} from 'node:module'
import {writeFile} from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const {chromium}=createRequire(path.resolve(process.argv[2],'package.json'))('playwright')
const browser=await chromium.launch({channel:'chrome'})
try{
 const page=await browser.newPage()
 await page.route('**/__supply-renderer',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><title>Supply renderer</title>'}))
 await page.goto(`${process.argv[3]}/__supply-renderer`)
 for(const name of ['feetech-wrist-adapter','feetech-wrist-frame','feetech-motor-tower','chain-a','chain-b']){
  const data=await page.evaluate(async name=>{
   const THREE=await import('/node_modules/three/build/three.module.js')
   const {STLLoader}=await import('/node_modules/three/examples/jsm/loaders/STLLoader.js')
   const geometry=await new STLLoader().loadAsync(`/assembly/supplies/${name}.stl`);geometry.center();geometry.computeVertexNormals()
   const scene=new THREE.Scene(),mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:'#34414a',roughness:.55}));scene.add(mesh)
   const bounds=new THREE.Box3().setFromObject(mesh),size=bounds.getSize(new THREE.Vector3()),extent=Math.max(size.x,size.y,size.z)
   if(size.z>size.y&&size.z>size.x)mesh.rotation.x=-Math.PI/2
   const camera=new THREE.OrthographicCamera(-extent*.72,extent*.72,extent*.72,-extent*.72,.1,extent*20)
   camera.position.set(extent*1.7,extent*1.1,extent*2);camera.lookAt(0,0,0)
   scene.add(new THREE.AmbientLight(0xffffff,1.6))
   for(const [x,y,z,intensity]of [[1,2,3,3],[-2,0,-1,2]]){const light=new THREE.DirectionalLight(0xffffff,intensity);light.position.set(x*extent,y*extent,z*extent);scene.add(light)}
   const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});renderer.setSize(1000,1000);renderer.setClearColor(0,0);renderer.render(scene,camera)
   const result=renderer.domElement.toDataURL('image/png').split(',')[1];geometry.dispose();mesh.material.dispose();renderer.dispose();return result
  },name)
  await writeFile(path.join(root,'frontend/public/assembly/supplies',`${name}.png`),Buffer.from(data,'base64'))
  console.log(`Rendered ${name}`)
 }
}finally{await browser.close()}

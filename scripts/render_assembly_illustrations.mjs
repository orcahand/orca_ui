// Run against Vite so the renderer uses the same CAD scenes as the interactive guide.
// node scripts/render_assembly_illustrations.mjs /path/to/playwright/tooling http://127.0.0.1:5178
import {createRequire} from 'node:module';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {chromium}=createRequire(path.resolve(process.argv[2]||'.','package.json'))('playwright');
const outputRoot=process.env.CAD_RENDER_OUTPUT_ROOT||root;
const origin=process.argv[3]||'http://127.0.0.1:5178';
const browser=await chromium.launch({channel:'chrome'});
try {
 const page=await browser.newPage();if(process.env.CAD_RENDER_OVERRIDE)await page.route(`**/assembly/parts/${process.argv[5]}/assembly.glb`,async r=>r.fulfill({body:await readFile(process.env.CAD_RENDER_OVERRIDE),contentType:'model/gltf-binary'}));await page.route('**/__illustration-renderer',r=>r.fulfill({contentType:'text/html',body:'<!doctype html><title>Assembly illustration renderer</title>'}));await page.goto(`${origin}/__illustration-renderer`);
 await page.evaluate(async()=>{
  const THREE=await import('/node_modules/three/build/three.module.js');
  const {RoomEnvironment}=await import('/node_modules/three/examples/jsm/environments/RoomEnvironment.js');
  const {loadBundle}=await import('/src/components/assembly/cadAssets.ts');
  const {CAD_ILLUSTRATIONS}=await import('/src/components/assembly/cadIllustrations.ts');
  const {illustrationScene}=await import('/src/components/assembly/cadIllustrationScene.ts');
  const width=1800,height=1400;
  const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
  renderer.setSize(width*2,height*2);renderer.setClearColor(0,0);renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;
  const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),environment=pmrem.fromScene(room,.04);
  const scene=new THREE.Scene();scene.environment=environment.texture;scene.environmentIntensity=.6;
  scene.add(new THREE.HemisphereLight('#ffffff','#5b6671',1.2));
  const key=new THREE.DirectionalLight('#fff8ee',2);scene.add(key);
  const fill=new THREE.DirectionalLight('#dcecff',1);scene.add(fill);
  const rim=new THREE.DirectionalLight('#ffffff',1);scene.add(rim);
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');
  window.renderIllustration=async(build,file)=>{
   const recipe=CAD_ILLUSTRATIONS.find(r=>r.file===file),bundle=await loadBundle(`${build.version}-${build.side}-dynamixel`);
   const model=illustrationScene(bundle,build,recipe);scene.add(model.group);model.group.updateMatrixWorld(true);
   // Imported surface normals preserve the exact CAD face curvature.

   const framing=model.frameObjects??[model.group];
   const box=new THREE.Box3();for(const object of framing)object.traverseVisible(n=>{if(n.isMesh&&(model.frameObjects||n.material.opacity>.3)){n.geometry.computeBoundingBox();box.union(n.geometry.boundingBox.clone().applyMatrix4(n.matrixWorld))}});
   if(model.focus)box.copy(model.focus);
   if(recipe.file==='panel-017-1'){const routes=(await import('/src/components/assembly/conduitRoutes.json')).default[`${build.version}-${build.side}`].carpals;box.makeEmpty();for(const path of routes)box.expandByPoint(new THREE.Vector3().fromArray(path.at(-1)));box.expandByScalar(7)}
   const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());
   const distance=size.length()*3,direction=model.direction.clone().normalize();
   const camera=new THREE.OrthographicCamera(-1,1,1,-1,.01,distance*4);
   if(Math.abs(direction.y)>.98)camera.up.set(0,0,1);
   if(model.up)camera.up.copy(model.up);
   camera.position.copy(center).addScaledVector(direction,distance);camera.lookAt(center);camera.updateMatrixWorld();
   const projected=new THREE.Box3();
   if(model.focus||recipe.file==='panel-017-1'){
    for(const x of[box.min.x,box.max.x])for(const y of[box.min.y,box.max.y])for(const z of[box.min.z,box.max.z])projected.expandByPoint(new THREE.Vector3(x,y,z).applyMatrix4(camera.matrixWorldInverse));
   }else for(const object of framing)object.traverseVisible(n=>{if(n.isMesh&&(model.frameObjects||n.material.opacity>.3)){const matrix=new THREE.Matrix4().multiplyMatrices(camera.matrixWorldInverse,n.matrixWorld),position=n.geometry.attributes.position,v=new THREE.Vector3();for(let i=0;i<position.count;i++)projected.expandByPoint(v.fromBufferAttribute(position,i).applyMatrix4(matrix))}});
   const view=projected.getSize(new THREE.Vector3()),half=Math.max(view.y/2,view.x/2/(width/height))*1.12;
   const middle=projected.getCenter(new THREE.Vector3());camera.top=middle.y+half;camera.bottom=middle.y-half;camera.left=middle.x-half*width/height;camera.right=middle.x+half*width/height;camera.updateProjectionMatrix();
   const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion),up=camera.up.clone().normalize();
   key.position.copy(center).addScaledVector(direction,distance).addScaledVector(up,distance).addScaledVector(right,-distance*.7);
   fill.position.copy(center).addScaledVector(direction,distance*.7).addScaledVector(right,distance);
   rim.position.copy(center).addScaledVector(direction,-distance).addScaledVector(up,distance);
   for(const light of[key,fill,rim]){light.target.position.copy(center);scene.add(light.target)}
   renderer.render(scene,camera);ctx.clearRect(0,0,width,height);ctx.drawImage(renderer.domElement,0,0,width,height);
   // A fine contour keeps exposed white cord legible against the pale surface.
   for(const points of model.cordOutlines??[]){
    ctx.beginPath();points.forEach((point,i)=>{const p=point.clone().applyMatrix4(model.group.matrixWorld).project(camera);ctx[i?'lineTo':'moveTo']((p.x+1)*width/2,(1-p.y)*height/2)});
    ctx.lineWidth=4;ctx.strokeStyle='#688879';ctx.stroke();ctx.lineWidth=2.5;ctx.strokeStyle='#ffffff';ctx.stroke();
   }
   // Keep naming leaders in the margins, ordered vertically to avoid crossed lines.
   ctx.font='600 42px system-ui';ctx.textBaseline='middle';
   const labels=model.labels.map(label=>label.text);
   const projectedLabels=model.labels.map(label=>{
    const point=label.point.clone().applyMatrix4(model.group.matrixWorld).project(camera);
    return {text:label.text,x:(point.x+1)*width/2,y:(1-point.y)*height/2};
   });
   for(const left of[true,false]){
    const items=projectedLabels.filter(p=>(p.x<width/2)===left).sort((a,b)=>a.y-b.y);
    items.forEach((p,i)=>{p.ty=Math.max(80,Math.min(height-80,p.y),i?items[i-1].ty+86:0)});
    const overflow=Math.max(0,(items.at(-1)?.ty??0)-(height-80));
    for(const p of items){
     const tx=left?36:width-36,ty=p.ty-overflow,textWidth=ctx.measureText(p.text).width;
     const end=left?tx+textWidth+16:tx-textWidth-16,elbow=end+(left?28:-28);
     ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(elbow,ty);ctx.lineTo(end,ty);
     ctx.lineWidth=7;ctx.strokeStyle='#f4faf5';ctx.stroke();ctx.lineWidth=3;ctx.strokeStyle='#285b45';ctx.stroke();
     ctx.fillStyle='#285b45';ctx.beginPath();ctx.arc(p.x,p.y,5,0,Math.PI*2);ctx.fill();
     ctx.fillStyle='rgba(237,245,239,.97)';ctx.fillRect(left?tx-8:tx-textWidth-8,ty-29,textWidth+16,58);
     ctx.textAlign=left?'left':'right';ctx.fillStyle='#24533f';ctx.fillText(p.text,tx,ty);
    }
   }
   const data=canvas.toDataURL('image/webp',.96).split(',')[1];scene.remove(model.group);model.dispose();
   return {data,labels,sourceSha256:bundle.inventory.source?.sha256,meshes:renderer.info.render.triangles,...(model.routePoints?{points:model.routePoints.map(point=>{const v=point.clone().applyMatrix4(model.group.matrixWorld).project(camera);return [(v.x+1)*width/2,(1-v.y)*height/2]}),names:model.names,width,height}:{})};
  };
  window.renderRecipes=CAD_ILLUSTRATIONS.map(({file,step})=>({file,step}));
 });
 const prefixes=process.argv[4]?.split(',');
 const recipes=(await page.evaluate(()=>window.renderRecipes)).filter(r=>!prefixes||prefixes.some(prefix=>r.file.startsWith(prefix))),manifest=[];
 for(const version of['base','touch'])for(const side of['right','left']){
  const key=`${version}-${side}-dynamixel`;if(process.argv[5]&&process.argv[5]!==key)continue;const folder=path.join(outputRoot,'frontend/public/assembly/renders',key);await mkdir(folder,{recursive:true});
  for(const recipe of recipes){const {data,...metadata}=await page.evaluate(({version,side,file})=>window.renderIllustration({version,side,motor:'dynamixel',audience:'internal'},file),{version,side,file:recipe.file});await writeFile(path.join(folder,`${recipe.file}.webp`),Buffer.from(data,'base64'));manifest.push({key,...recipe,...metadata});}
  console.log(`Rendered ${key}: ${recipes.length} illustrations`);
 }
 const routing=Object.fromEntries(manifest.filter(m=>m.points).map(({key,file,...metadata})=>[`${key}/${file}`,metadata]));
 if(Object.keys(routing).length){const file=path.join(outputRoot,'frontend/src/components/assembly/cad-route-views.json');let previous={};try{previous=JSON.parse(await readFile(file,'utf8'))}catch{}await writeFile(file,JSON.stringify({...previous,...routing},null,2)+'\n');}
 const manifestFile=path.join(outputRoot,'frontend/public/assembly/renders/manifest.json');
 let entries=manifest;
 if(process.argv[4]||process.argv[5]){let previous=[];try{previous=JSON.parse(await readFile(manifestFile,'utf8'))}catch{}const replaced=new Set(manifest.map(m=>`${m.key}/${m.file}`));entries=[...previous.filter(m=>!replaced.has(`${m.key}/${m.file}`)),...manifest];}
 await writeFile(manifestFile,JSON.stringify(entries,null,2)+'\n');
} finally {await browser.close()}

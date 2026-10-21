// Render the imported meshes with smooth lighting; requires Playwright in a tooling directory.
// node scripts/render_assembly_thumbnails.mjs /path/to/tooling http://127.0.0.1:5002
import {createRequire} from 'node:module';
import {readFile,writeFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {chromium}=createRequire(path.resolve(process.argv[2]||'.','package.json'))('playwright');
const origin=process.argv[3]||'http://127.0.0.1:5002';
const browser=await chromium.launch({channel:'chrome'});
try {
  for(const entry of await readdir(path.join(root,'frontend/public/assembly/parts'),{withFileTypes:true})) {
    if(!entry.isDirectory()||(process.argv[4]&&!entry.name.startsWith(process.argv[4])))continue;
    const key=entry.name,folder=path.join(root,'frontend/public/assembly/parts',key),inventory=JSON.parse(await readFile(path.join(folder,'inventory.json'),'utf8'));
    const page=await browser.newPage();
    await page.route('**/__cadtools/**',async route=>{
      const relative=new URL(route.request().url()).pathname.split('/__cadtools/')[1];
      const file=path.resolve(root,'frontend/node_modules',relative);
      if(!file.startsWith(path.join(root,'frontend/node_modules')+path.sep))return route.abort();
      await route.fulfill({body:await readFile(file),contentType:'text/javascript'});
    });
    await page.goto(origin);await page.waitForLoadState("networkidle");
    await page.setContent('<script type="importmap">{"imports":{"three":"/__cadtools/three/build/three.module.js"}}</script>');
    await page.evaluate(async key=>{
      const THREE=await import('/__cadtools/three/build/three.module.js');
      const {RoomEnvironment}=await import('/__cadtools/three/examples/jsm/environments/RoomEnvironment.js');
      const {GLTFLoader}=await import('/__cadtools/three/examples/jsm/loaders/GLTFLoader.js');
      const gltf=await new GLTFLoader().loadAsync(`/assembly/parts/${key}/assembly.glb`);
      gltf.scene.updateMatrixWorld(true);
      const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});renderer.setSize(1040,840);renderer.setPixelRatio(1);renderer.setClearColor(0,0);
      renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
      const scene=new THREE.Scene(),pmrem=new THREE.PMREMGenerator(renderer),environment=pmrem.fromScene(new RoomEnvironment(),.04);scene.environment=environment.texture;scene.environmentIntensity=.6;scene.add(new THREE.HemisphereLight('#ffffff','#5b6671',1.2));const keyLight=new THREE.DirectionalLight('#f4f9ff',2);keyLight.position.set(3,5,7);scene.add(keyLight);const fill=new THREE.DirectionalLight('#c7e0ec',1);fill.position.set(-4,1,-2);scene.add(fill);
      const camera=new THREE.OrthographicCamera(-1.24,1.24,1,-1,.01,50);camera.position.set(0,0,10);
      window.renderPart=part=>{
        const node=gltf.scene.getObjectByName(part.nodes[0]);let source;node.traverse(n=>{if(n.isMesh&&!source)source=n});
        const geometry=source.geometry;geometry.computeBoundingBox();const extent=geometry.boundingBox.getSize(new THREE.Vector3()),center=geometry.boundingBox.getCenter(new THREE.Vector3());
        const skin=part.category==='Skins',metal=part.category==='Standard components';
        const boardColors=part.label==='OH control board'&&!!geometry.getAttribute('color');
        const material=new THREE.MeshStandardMaterial({color:boardColors?'#ffffff':skin?(key.startsWith('base')?(part.label==='Palm skin'?'#29333b':'#e9eded'):'#161b20'):metal?'#b5bcc3':part.category==='Tendons'?'#318b94':/OH control board/.test(part.label)?'#171c1b':/board|PCB/.test(part.label)?'#171c1b':'#29333b',vertexColors:boardColors,roughness:skin?.76:metal?.3:.48,metalness:metal?.55:0});
        const mesh=new THREE.Mesh(geometry,material),group=new THREE.Group();mesh.position.copy(center).negate();group.add(mesh);group.rotation.set(.4,-.65,.08);scene.add(group);
        const bounds=new THREE.Box3().setFromObject(group),size=bounds.getSize(new THREE.Vector3());group.scale.setScalar(1.55/Math.max(size.y,size.x/1.24));const framed=new THREE.Box3().setFromObject(group);group.position.sub(framed.getCenter(new THREE.Vector3()));
        renderer.render(scene,camera);const data=renderer.domElement.toDataURL('image/png');scene.remove(group);material.dispose();return data.split(',')[1];
      };
    },key);
    const parts=inventory.parts.filter(p=>!process.argv[5]||p.id===process.argv[5]);
    for(const part of parts){const data=await page.evaluate(part=>window.renderPart(part),part);await writeFile(path.join(folder,`${part.id}.png`),Buffer.from(data,'base64'));}
    await page.close();console.log('Rendered',key,parts.length,'illustrations');
  }
} finally {await browser.close();}

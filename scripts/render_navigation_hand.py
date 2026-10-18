"""Render the sidebar hand and matching click regions from CAD.

Requires Python Playwright with Chrome and a running Vite server.
Usage: python scripts/render_navigation_hand.py http://127.0.0.1:5181
"""
import base64
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'frontend/public/assembly/navigation'
DEST.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome')
    page = browser.new_page()
    page.route('**/__navigation-render', lambda r: r.fulfill(content_type='text/html', body='<script type="importmap">{"imports":{"three":"/node_modules/three/build/three.module.js"}}</script>'))
    page.goto((sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:5181')+'/__navigation-render')
    result = page.evaluate('''async()=>{
      const THREE=await import('/node_modules/three/build/three.module.js');
      const {RoomEnvironment}=await import('/node_modules/three/examples/jsm/environments/RoomEnvironment.js');
      const {loadBundle}=await import('/src/components/assembly/cadAssets.ts');
      const {cadPieces,disposePieces}=await import('/src/components/assembly/cadScene.ts');
      const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true});renderer.setSize(640,900);renderer.setPixelRatio(2);renderer.setClearColor(0,0);
      renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1;
      const scene=new THREE.Scene(),pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();scene.environment=pmrem.fromScene(room,.04).texture;
      scene.environmentIntensity=.65;scene.add(new THREE.HemisphereLight(0xffffff,0x64727a,1.4));
      for(const [pos,power] of [[[200,500,400],2],[[-300,150,200],.8]]){const light=new THREE.DirectionalLight(0xffffff,power);light.position.set(...pos);scene.add(light)}
      const output={};
      for(const version of ['base','touch']){
        const build={version,side:'right',motor:'dynamixel',audience:'internal'},bundle=await loadBundle(`${version}-right-dynamixel`),pieces=cadPieces(bundle,build),group=new THREE.Group();
        const selected=pieces.filter(p=>p.part.category!=='Tendons'&&!p.part.label.includes('(optional)')&&!(version==='touch'&&/DP skin|Pinky touch skin/.test(p.part.label)));
        selected.forEach(p=>group.add(p.object));scene.add(group);group.updateMatrixWorld(true);
        const box=new THREE.Box3().setFromObject(group),center=box.getCenter(new THREE.Vector3()),camera=new THREE.OrthographicCamera(-1,1,1,-1,.1,3000);
        camera.position.copy(center).add(new THREE.Vector3(.5,.05,-1).normalize().multiplyScalar(1000));camera.lookAt(center);camera.updateMatrixWorld();
        const projected=new THREE.Box3();group.traverse(n=>{if(n.isMesh){const matrix=new THREE.Matrix4().multiplyMatrices(camera.matrixWorldInverse,n.matrixWorld),v=new THREE.Vector3(),a=n.geometry.attributes.position;for(let i=0;i<a.count;i++)projected.expandByPoint(v.fromBufferAttribute(a,i).applyMatrix4(matrix))}});
        const size=projected.getSize(new THREE.Vector3()),mid=projected.getCenter(new THREE.Vector3()),half=Math.max(size.y/2,size.x/2/(640/900))*1.07;
        camera.left=mid.x-half*640/900;camera.right=mid.x+half*640/900;camera.top=mid.y+half;camera.bottom=mid.y-half;camera.updateProjectionMatrix();
        const regions={thumb:[],index:[],middle:[],ring:[],pinky:[],palm:[],wrist:[],tower:[]};
        for(const piece of selected){
          const label=piece.part.label;
          let region=['thumb','index','middle','ring','pinky'].find(f=>label.toLowerCase().startsWith(f+' ')&&/ (DP|PP|AP|TP)( skin)?$/.test(label));
          if(label==='Middle / ring DP skin'){const dp=pieces.filter(p=>/^(Middle|Ring) DP$/.test(p.part.label)).sort((a,b)=>a.center.distanceToSquared(piece.center)-b.center.distanceToSquared(piece.center))[0];region=dp.part.label.split(' ')[0].toLowerCase()}
          if(['Carpals','Touch carpals','Carpal core','Palm skin'].includes(label))region='palm';
          if(['Wrist frame','Wrist pulley','Wrist motor adapter'].includes(label))region='wrist';
          if(['Hull cover','Rear hull cover','Motor tower'].includes(label))region='tower';
          if(!region)continue;
          const b=new THREE.Box2();piece.object.traverse(n=>{if(n.isMesh){const v=new THREE.Vector3(),a=n.geometry.attributes.position;for(let i=0;i<a.count;i++){v.fromBufferAttribute(a,i).applyMatrix4(n.matrixWorld).project(camera);b.expandByPoint(new THREE.Vector2((v.x+1)*320,(1-v.y)*450))}}});
          regions[region].push([b.min.x,b.min.y,b.max.x-b.min.x,b.max.y-b.min.y].map(n=>Math.round(n*10)/10));
        }
        renderer.render(scene,camera);const canvas=document.createElement('canvas');canvas.width=640;canvas.height=900;canvas.getContext('2d').drawImage(renderer.domElement,0,0,640,900);
        output[version]={image:canvas.toDataURL('image/webp',.96).split(',')[1],regions,sourceSha256:bundle.inventory.source?.sha256};
        scene.remove(group);disposePieces(pieces);
      }
      return output;
    }''')
    for version, data in result.items():
        (DEST/f'{version}-right.webp').write_bytes(base64.b64decode(data.pop('image')))
    (ROOT/'frontend/src/components/assembly/navigationHand.json').write_text(json.dumps(result,indent=2)+'\n')
    browser.close()

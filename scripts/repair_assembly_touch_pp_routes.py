"""Repair Touch DP flexion through the internal PP passage using current GLB surfaces.

Requires NumPy. Writes a staging JSON for review; never modifies source meshes.
Example: python scripts/repair_assembly_touch_pp_routes.py --output /tmp/routes.json
"""
import argparse, heapq, itertools, json, struct
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
routes=json.loads((ROOT/'frontend/src/components/assembly/channelRoutes.json').read_text())
frames=json.loads((ROOT/'frontend/src/components/assembly/jointFrames.json').read_text())
def mesh(key,label='Index PP'):
 p=ROOT/'frontend/public/assembly/parts'/f'{key}-dynamixel';b=(p/'assembly.glb').read_bytes();n=struct.unpack_from('<I',b,12)[0];d=json.loads(b[20:20+n]);raw=b[28+n:]
 def a(i):
  q=d['accessors'][i];v=d['bufferViews'][q['bufferView']];return np.frombuffer(raw,dtype={5126:'<f4',5125:'<u4',5123:'<u2'}[q['componentType']],count=q['count']*({'VEC3':3,'SCALAR':1}[q['type']]),offset=v.get('byteOffset',0)+q.get('byteOffset',0)).reshape(q['count'],-1).copy()
 inv=json.loads((p/'inventory.json').read_text());names=next(x['nodes'] for x in inv['parts'] if x['label']==label)
 x=next(x for x in d['nodes'] if x.get('name')==names[0]);prim=d['meshes'][x['mesh']]['primitives'][0];v=a(prim['attributes']['POSITION']);m=np.array(x.get('matrix',np.eye(4).T.flatten())).reshape(4,4).T;v=v@m[:3,:3].T+m[:3,3];return v,a(prim['indices']).ravel().reshape(-1,3)
metadata=json.loads((ROOT/'frontend/src/components/assembly/cadGeometry.json').read_text())
for key in ['touch-right','touch-left']:
 fr=frames[key]['Index'];basis=np.array([fr[a]for a in ['x','y','z']]);origin=np.array(fr['origin']);world=lambda p:np.array(p)@basis+origin;local=lambda p:(np.array(p)-origin)@basis.T
 v,f=mesh(key);tri=local(v)[f];mins=tri.min(1);maxs=tri.max(1)
 def crossing(x,z):
  t=tri[(mins[:,0]-1e-8<=x)&(maxs[:,0]+1e-8>=x)&(mins[:,2]-1e-8<=z)&(maxs[:,2]+1e-8>=z)];a=t[:,0];b=t[:,1]-a;c=t[:,2]-a;det=b[:,0]*c[:,2]-c[:,0]*b[:,2];valid=abs(det)>1e-10;u=np.divide((x-a[:,0])*c[:,2]-(z-a[:,2])*c[:,0],det,out=np.zeros(len(det)),where=valid);w=np.divide(b[:,0]*(z-a[:,2])-b[:,2]*(x-a[:,0]),det,out=np.zeros(len(det)),where=valid);ok=valid&(u>=-1e-8)&(w>=-1e-8)&(u+w<=1+1e-8);return np.unique(np.round(a[ok,1]+u[ok]*b[ok,1]+w[ok]*c[ok,1],5))
 base='base-'+key.split('-')[1];bf=frames[base]['Index'];bb=np.array([bf[a]for a in ['x','y','z']]);bo=np.array(bf['origin']);p=(np.array(routes[base]['p33'][0]['fixed'])-bo)@bb.T
 # Side-wall offsets differ in the supplied assemblies; use the actual PP surfaces.
 bv,bfaces=mesh(base);bv=(bv-bo)@bb.T;p[:,1]+=mins[:,1].min()-bv[:,1].min()
 changed=0
 for point in p:
  if point[2]<18:continue
  hits=crossing(point[0],point[2]);gaps=[(a,b) for a,b in zip(hits[1::2],hits[2::2]) if b-a>.3]
  if gaps:
   a,b=min(gaps,key=lambda ab:abs((ab[0]+ab[1])/2-point[1]))
   if not a+.18<=point[1]<=b-.18:point[1]=(a+b)/2;changed+=1
 # Check complete cord envelopes against the owning PP, not merely the centreline.
 def inside(point):
  hits=crossing(point[0],point[2]);return np.count_nonzero(hits<point[1])%2==1
 offsets=[np.zeros(3),*[np.array(q)/np.linalg.norm(q)*.16 for q in itertools.product([-1,0,1],repeat=3)if any(q)]]
 moving=local(routes[key]['p33'][0]['moving'])
 # Find the short entrance bend between the DP outlet and PP's internal passage.
 pp_tri,pp_min,pp_max=tri,mins,maxs
 dv,df=mesh(key,'Index DP');dp_tri=local(dv)[df]
 pp_cross=crossing
 step=.1;ycenter=p[0,1]
 axes=[np.arange(-9.05,-3.65,step),np.arange(ycenter-1.6,ycenter+.7,step),np.arange(29.4,33.1,step)]
 shape=tuple(map(len,axes));solid=np.zeros(shape,dtype=bool)
 for body in [pp_tri,dp_tri]:
  tri=body;mins=tri.min(1);maxs=tri.max(1)
  for ix,x in enumerate(axes[0]):
   for iz,z in enumerate(axes[2]):
    h=crossing(x,z)
    solid[ix,:,iz]|=np.sum(axes[1][:,None]>h,axis=1)%2==1
 valid=~solid
 for q in itertools.product(range(-3,4),repeat=3):
  if np.linalg.norm(q)*step>.28:continue
  shifted=np.roll(solid,q,axis=(0,1,2));valid&=~shifted
 coords=np.stack(np.meshgrid(*axes,indexing='ij'),-1)
 free_ids=np.argwhere(valid);free_pts=coords[valid]
 def seed(target):return tuple(free_ids[np.linalg.norm(free_pts-target,axis=1).argmin()])
 start=seed(moving[-1]);end=seed(p[0]);import heapq
 neighbors=[np.array(q) for q in itertools.product([-1,0,1],repeat=3) if any(q)]
 queue=[(0.,0.,start)];cost={start:0.};back={}
 while queue:
  _,g,node=heapq.heappop(queue)
  if cost[node]!=g:continue
  if node==end:break
  for q in neighbors:
   nxt=np.array(node)+q;t=tuple(nxt)
   if np.any(nxt<0) or np.any(nxt>=shape) or not valid[t]:continue
   ng=g+np.linalg.norm(q)
   if ng<cost.get(t,float('inf')):cost[t]=ng;back[t]=node;heapq.heappush(queue,(ng+np.linalg.norm(nxt-np.array(end)),ng,t))
 assert end in cost,('No entrance passage',key)
 chain=[end]
 while chain[-1]!=start:chain.append(back[chain[-1]])
 entrance=np.array([coords[q] for q in reversed(chain)])
 p=np.vstack([entrance,p])
 tri=pp_tri;mins=pp_min;maxs=pp_max
 check=np.vstack([moving[-1],p])
 dense=np.vstack([a+(b-a)*np.linspace(0,1,max(2,int(np.linalg.norm(b-a)/.04)+1))[:,None] for a,b in zip(check,check[1:])])
 failures=[]
 for i,point in enumerate(dense):
  if any(inside(point+off) for off in offsets):failures.append(i)
 inv=json.loads((ROOT/f'frontend/public/assembly/parts/{key}-dynamixel/inventory.json').read_text())
 pin_clearance=float('inf')
 for part in inv['parts']:
  if not part['label'].startswith('Pin'):continue
  for name in part['nodes']:
   center=np.array(metadata[key][name]['center'])
   if not np.all((center>=v.min(0)-1)&(center<=v.max(0)+1)):continue
   axis=np.array(metadata[key][name]['axis']);axis/=np.linalg.norm(axis);half=float(part['label'].split('×')[-1])/2
   delta=world(dense)-center;axial=np.clip(delta@axis,-half,half);pin_clearance=min(pin_clearance,np.linalg.norm(delta-axial[:,None]*axis,axis=1).min()-1)
 # Recheck the fixed route and joining span against the seated DP as well.
 dv,df=mesh(key,'Index DP');tri=local(dv)[df];mins=tri.min(1);maxs=tri.max(1)
 dp_fail=[i for i,point in enumerate(dense) if any(inside(point+off) for off in offsets)]
 print('DP failures',len(dp_fail),dense[dp_fail[:5]].round(3),flush=True)
 print('pin clearance',key,pin_clearance,flush=True)
 print(key,'changed y',changed,'failed',len(failures),dense[failures[::max(1,len(failures)//8)]].round(3) if failures else [],flush=True)
 routes[key]['p33'][0]['fixed']=world(p).round(5).tolist()
 assert not failures and not dp_fail and pin_clearance>.16, ('Route clearance failed',key)
args.output.write_text(json.dumps(routes,separators=(',',':'))+'\n')

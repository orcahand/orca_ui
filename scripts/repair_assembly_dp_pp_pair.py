"""Pair the Index DP flexion path with DP extension inside PP, for Base and Touch.

Preserves DP anchors, extension routing and the original free ends. Requires NumPy.
Writes staging data only; review and copy it to channelRoutes.json, then rerender
panel-034-[456], panel-036-[12] and route-p35-pair with the illustration renderer.
Supersedes the old Touch-only PP route repair.
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
for key in routes:
 fr=frames[key]['Index'];basis=np.array([fr[a]for a in ['x','y','z']]);origin=np.array(fr['origin']);local=lambda p:(np.array(p)-origin)@basis.T;world=lambda p:np.array(p)@basis+origin
 # Keep the DP anchor and outlet; pair the PP run with the extension tendon.
 start=local(routes[key]['p33'][0]['moving'][-1]);fixed=local(routes[key]['p33'][1]['fixed']);turn=np.clip((17-fixed[:,2])/4,0,1)*np.pi/2
 # The channel widens below the upper run; shift across its depth before the pins.
 fixed[:,0]-=.4*np.cos(turn);fixed[:,1]-=.4*np.sin(turn);end=fixed[0]
 # Return to the existing free end only beyond the PP solid (z < -9.5).
 old_end=local(routes[key]['p33'][0]['fixed'][-1]);blend=np.clip((-fixed[:,2]-9.85)/2.1,0,1);fixed+=blend[:,None]*(old_end-fixed[-1]);fixed[-1]=old_end
 # Find the joining bend in the seated joint, with clearance from DP, PP and pins.
 step=.2;axes=[np.arange(-10,7.01,step),np.arange(end[1]-3,end[1]+3.01,step),np.arange(24,35.01,step)];shape=tuple(map(len,axes));solid=np.zeros(shape,dtype=bool)
 def crossing(x,z):
  t=tri[(mins[:,0]-1e-8<=x)&(maxs[:,0]+1e-8>=x)&(mins[:,2]-1e-8<=z)&(maxs[:,2]+1e-8>=z)];a=t[:,0];b=t[:,1]-a;c=t[:,2]-a;det=b[:,0]*c[:,2]-c[:,0]*b[:,2];valid=abs(det)>1e-10;u=np.divide((x-a[:,0])*c[:,2]-(z-a[:,2])*c[:,0],det,out=np.zeros(len(det)),where=valid);w=np.divide(b[:,0]*(z-a[:,2])-b[:,2]*(x-a[:,0]),det,out=np.zeros(len(det)),where=valid);ok=valid&(u>=-1e-8)&(w>=-1e-8)&(u+w<=1+1e-8);return np.unique(np.round(a[ok,1]+u[ok]*b[ok,1]+w[ok]*c[ok,1],5))
 for body in ['Index PP','Index DP']:
  v,f=mesh(key,body);tri=local(v)[f];mins=tri.min(1);maxs=tri.max(1)
  for ix,x in enumerate(axes[0]):
   for iz,z in enumerate(axes[2]):
    hits=crossing(x,z);solid[ix,:,iz]|=np.sum(axes[1][:,None]>hits,axis=1)%2==1
 valid=~solid
 for q in itertools.product(range(-2,3),repeat=3):
  if np.linalg.norm(q)*step<=.3:valid&=~np.roll(solid,q,axis=(0,1,2))
 coords=np.stack(np.meshgrid(*axes,indexing='ij'),-1)
 v,f=mesh(key,'Index PP')
 inv=json.loads((ROOT/f'frontend/public/assembly/parts/{key}-dynamixel/inventory.json').read_text())
 for part in inv['parts']:
  if not part['label'].startswith('Pin'):continue
  for name in part['nodes']:
   center=np.array(metadata[key][name]['center'])
   if not np.all((center>=v.min(0)-1)&(center<=v.max(0)+1)):continue
   axis=np.array(metadata[key][name]['axis']);axis/=np.linalg.norm(axis);axis=axis@basis.T;center=local(center);half=float(part['label'].split('×')[-1])/2
   delta=coords-center;axial=np.clip(delta@axis,-half,half);valid&=np.linalg.norm(delta-axial[...,None]*axis,axis=-1)>1.25
 free_ids=np.argwhere(valid);free_pts=coords[valid]
 def seed(target):return tuple(free_ids[np.linalg.norm(free_pts-target,axis=1).argmin()])
 first=seed(start);last=seed(end);print(key,'start',start,'seed',coords[first],'end',end,'seed',coords[last],flush=True)
 neighbors=[(np.array(q),np.linalg.norm(q)) for q in itertools.product([-1,0,1],repeat=3) if any(q)]
 queue=[(0.,0.,first)];cost={first:0.};back={}
 while queue:
  _,g,node=heapq.heappop(queue)
  if cost[node]!=g:continue
  if node==last:break
  for q,distance in neighbors:
   nxt=np.array(node)+q;t=tuple(nxt)
   if np.any(nxt<0) or np.any(nxt>=shape) or not valid[t]:continue
   ng=g+distance
   if ng<cost.get(t,float('inf')):cost[t]=ng;back[t]=node;heapq.heappush(queue,(ng+np.linalg.norm(nxt-np.array(last)),ng,t))
 assert last in cost,('No passage',key,len(cost))
 chain=[last]
 while chain[-1]!=first:chain.append(back[chain[-1]])
 entrance=np.array([coords[q] for q in reversed(chain)])
 # Validate the rendered 0.14 mm cord using a slightly larger sampled envelope.
 candidate=np.vstack([start,entrance,fixed])
 dense=np.vstack([a+(b-a)*np.linspace(0,1,max(2,int(np.linalg.norm(b-a)/.05)+1))[:,None] for a,b in zip(candidate,candidate[1:])])
 offsets=[np.zeros(3),*[np.array(q)/np.linalg.norm(q)*.15 for q in itertools.product([-1,0,1],repeat=3) if any(q)]]
 for body in ['Index PP','Index DP']:
  v,f=mesh(key,body);tri=local(v)[f];mins=tri.min(1);maxs=tri.max(1);failed=[]
  for i,point in enumerate(dense):
   for off in offsets:
    q=point+off
    if np.count_nonzero(crossing(q[0],q[2])<q[1])%2:failed.append(i);break
  print(key,body,'clearance failures',len(failed),dense[failed[:8]].round(3),flush=True)
  assert not failed
 v,f=mesh(key,'Index PP');minimum=float('inf')
 for part in inv['parts']:
  if not part['label'].startswith('Pin'):continue
  for name in part['nodes']:
   center=np.array(metadata[key][name]['center'])
   if not np.all((center>=v.min(0)-1)&(center<=v.max(0)+1)):continue
   axis=np.array(metadata[key][name]['axis']);axis/=np.linalg.norm(axis);half=float(part['label'].split('×')[-1])/2
   delta=world(dense)-center;axial=np.clip(delta@axis,-half,half);minimum=min(minimum,np.linalg.norm(delta-axial[:,None]*axis,axis=1).min()-1)
 print(key,'minimum pin clearance',round(minimum,3),flush=True)
 assert minimum>.15,('Pin clearance failed',key,minimum)
 routes[key]['p33'][0]['fixed']=world(np.vstack([entrance,fixed])).round(5).tolist()
args.output.write_text(json.dumps(routes,separators=(',',':'))+'\n')

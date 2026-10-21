"""Check cord-radius clearance against the PP solid and its three installed pins."""
from pathlib import Path
import json,heapq,itertools,argparse
import numpy as np,cadquery as cq,trimesh
from scipy.spatial import cKDTree
from cad_render_mesh import render_mesh
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Repair PP tendon paths around the seated STEP pins; write reviewed results to a staging file.')
parser.add_argument('--base-breps',type=Path,required=True)
parser.add_argument('--touch-breps',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
routes=json.loads((ROOT/'frontend/src/components/assembly/channelRoutes.json').read_text())
metadata=json.loads((ROOT/'frontend/src/components/assembly/cadGeometry.json').read_text())
report={}
for key in ['base-right','base-left','touch-right','touch-left']:
 source=args.touch_breps if key.startswith('touch') else args.base_breps
 solid=cq.Shape.importBrep(str(source/f'{key}-Index-PP.brep'));bounds=solid.BoundingBox()
 inventory=json.loads((ROOT/f'frontend/public/assembly/parts/{key}-dynamixel/inventory.json').read_text())
 pins=[]
 for part in inventory['parts']:
  if not part['label'].startswith('Pin'):continue
  for node in part['nodes']:
   p=metadata[key][node];center=np.array(p['center'])
   if np.all(center>=np.array([bounds.xmin,bounds.ymin,bounds.zmin])-1)and np.all(center<=np.array([bounds.xmax,bounds.ymax,bounds.zmax])+1):pins.append(dict(p,label=part['label']))
 assert len(pins)==3, (key,'expected three PP pins',len(pins))
 short=[p for p in pins if p['label'].endswith('6')]
 assert len(short)==2, (key,'expected two 2 × 6 pins')
 centers=[np.array(p['center'])for p in short];origin=np.mean(centers,axis=0);u=np.array(short[0]['axis']);u/=np.linalg.norm(u);v=centers[1]-centers[0];v-=u*np.dot(u,v);v/=np.linalg.norm(v);w=np.cross(u,v);basis=np.array([u,v,w]).T
 mesh=render_mesh(solid,.035,.12);mesh.ray=trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
 directions=np.array([np.array(p)/np.linalg.norm(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)])*.18
 def free(points,body_clearance=.18):
  points=np.asarray(points).reshape(-1,3);ok=np.ones(len(points),dtype=bool)
  for pin in pins:
   center=np.array(pin['center']);axis=np.array(pin['axis']);axis/=np.linalg.norm(axis);half=float(pin['label'].split('×')[-1])/2
   delta=points-center;t=np.clip(delta@axis,-half,half);ok&=np.linalg.norm(delta-t[:,None]*axis,axis=1)>1.2
  for offset in [np.zeros(3),*(directions*(body_clearance/.18))]:
   ids=np.flatnonzero(ok)
   if not len(ids):break
   ok[ids]&=~mesh.contains(points[ids]+offset)
  return ok
 def dense(points,spacing=.08):
  return np.concatenate([a+(b-a)*np.linspace(0,1,max(2,int(np.linalg.norm(b-a)/spacing)+1))[:,None] for a,b in zip(points,points[1:])])
 neighbors=[np.array(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)]
 previous=[];report[key]=[]
 for number,route in enumerate(routes[key]['p33']):
  points=np.array(route['fixed'])
  if free(dense(points),.14).all():
   print(key,number,'already clears the PP and pins',flush=True);previous.extend(points);continue
  near=np.flatnonzero(np.linalg.norm(points-origin,axis=1)<6)
  start=max(0,near[0]-3);end=min(len(points)-1,near[-1]+3);local=(points[start:end+1]-origin)@basis
  lo=local.min(axis=0)-[1.2,2.5,3];hi=local.max(axis=0)+[1.2,2.5,3];step=.22;shape=np.ceil((hi-lo)/step).astype(int)+1
  coords=np.indices(shape).reshape(3,-1).T;world=(lo+coords*step)@basis.T+origin
  print(key,number,'grid',shape,len(world),flush=True)
  valid=free(world)
  if previous:valid&=cKDTree(previous).query(world)[0]>.36
  valid=valid.reshape(shape);grid=world.reshape(*shape,3)
  def seed(target):
   idx=np.round(((target-origin)@basis-lo)/step).astype(int);candidates=[idx+q for q in neighbors]+[idx];candidates=[tuple(q)for q in candidates if np.all(q>=0)and np.all(q<shape)and valid[tuple(q)]]
   candidates.sort(key=lambda q:np.linalg.norm(grid[q]-target))
   for q in candidates:
    if free(dense([target,grid[q]])).all():return q
   raise RuntimeError(('No free seed',key,number,target,idx))
  midpoint=origin+u*np.dot(points[np.argmin(np.linalg.norm(points-origin,axis=1))]-origin,u)
  a=seed(points[start]);b=seed(midpoint);c=seed(points[end])
  def astar(a,b):
   queue=[(0,0,a)];cost={a:0};back={};dest=np.array(b)
   while queue:
    _,g,node=heapq.heappop(queue)
    if g!=cost[node]:continue
    if node==b:
     path=[node]
     while node!=a:node=back[node];path.append(node)
     return [grid[i]for i in reversed(path)]
    n=np.array(node)
    for offset in neighbors:
     nxt=n+offset;t=tuple(nxt)
     if np.any(nxt<0)or np.any(nxt>=shape)or not valid[t]:continue
     if any(not valid[tuple(n+np.eye(3,dtype=int)[i]*offset[i])]for i in range(3)if offset[i]):continue
     ng=g+np.linalg.norm(offset)
     if ng<cost.get(t,float('inf')):cost[t]=ng;back[t]=node;heapq.heappush(queue,(ng+np.linalg.norm(nxt-dest),ng,t))
   raise RuntimeError(('No path',key,number,a,b))
  path=np.array([points[start],*astar(a,b),*astar(b,c)[1:],points[end]])
  # Shorten only when the complete cord radius still clears printed material and pins.
  simplified=[path[0]];i=0
  while i<len(path)-1:
   j=min(len(path)-1,i+18)
   while j>i+1 and not free(dense([path[i],path[j]])).all():j-=1
   simplified.append(path[j]);i=j
  repair=dense(np.array(simplified),.15)
  assert free(dense(repair,.04)).all(),('repair collision',key,number)
  updated=np.concatenate([points[:start],repair,points[end+1:]])
  route['fixed']=np.round(updated,5).tolist();previous.extend(repair)
  report[key].append(dict(points=len(updated),replaced=[int(start),int(end)],waypoint=midpoint.tolist()))
  print(key,number,'repaired',len(updated),flush=True)
args.output.write_text(json.dumps(routes,separators=(',',':'))+'\n')
args.output.with_suffix('.report.json').write_text(json.dumps(report,indent=2))

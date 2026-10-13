"""Derive illustration paths from the PP knot pocket to its two tendon exits."""
from pathlib import Path
import json,heapq,itertools,argparse
import numpy as np,cadquery as cq,trimesh
from scipy.spatial import cKDTree
from OCP.BRepAdaptor import BRepAdaptor_Surface
from cad_render_mesh import render_mesh
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Plan PP anchor cords from the STEP knot pocket, checking the assembled joint and pins.')
parser.add_argument('--base-breps',type=Path,required=True)
parser.add_argument('--touch-breps',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--config',action='append',choices=['base-right','base-left','touch-right','touch-left'])
args=parser.parse_args()
F=json.load(open(ROOT/'frontend/src/components/assembly/jointFrames.json'));P=json.load(open(ROOT/'frontend/src/components/assembly/connectorPorts.json'));G=json.load(open(ROOT/'frontend/src/components/assembly/cadGeometry.json'));R=json.load(open(ROOT/'frontend/src/components/assembly/channelRoutes.json'));out={}
out=json.loads(args.output.read_text())if args.output.exists()else{}
for key in (args.config or list(F)):
 root=args.touch_breps if key.startswith('touch')else args.base_breps;solids=[cq.Shape.importBrep(str(root/(key+'-Index-'+seg+'.brep')))for seg in ['PP','AP']];meshes=[render_mesh(s,.035,.12)for s in solids]
 for mesh in meshes:mesh.ray=trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
 frame=F[key]['Index'];basis=np.array([frame[a]for a in ['x','y','z']]);cavities=[]
 for face in solids[0].Faces():
  a=BRepAdaptor_Surface(face.wrapped)
  if str(a.GetType()).endswith('Cylinder')and abs(a.Cylinder().Radius()-1.5)<.01 and a.LastUParameter()-a.FirstUParameter()>6 and int(face.wrapped.Orientation())==1:
   cy=a.Cylinder();c=np.array(cy.Location().Coord());axis=np.array(cy.Axis().Direction().Coord());cavities.append(c+axis*(a.FirstVParameter()+a.LastVParameter())/2)
 assert len(cavities)==1;origin=cavities[0];bbox=solids[0].BoundingBox();loWorld=np.array([bbox.xmin,bbox.ymin,bbox.zmin]);hiWorld=np.array([bbox.xmax,bbox.ymax,bbox.zmax]);inv=json.load(open(ROOT/f'frontend/public/assembly/parts/{key}-dynamixel/inventory.json'));pins=[]
 for part in inv['parts']:
  if not part['label'].startswith('Pin'):continue
  for node in part['nodes']:
   data=G[key][node];c=np.array(data['center'])
   if np.all(c>=loWorld-1)and np.all(c<=hiWorld+1):pins.append((c,np.array(data['axis']),float(part['label'].split('×')[-1])/2))
 assert len(pins)==3
 others=np.concatenate([np.array(p['fixed'])for p in R[key]['p33']]);tree=cKDTree(others);dirs=np.array([np.array(p)/np.linalg.norm(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)])*.18
 def free(points):
  points=np.asarray(points).reshape(-1,3);ok=tree.query(points)[0]>.36
  for center,axis,half in pins:
   delta=points-center;t=np.clip(delta@axis,-half,half);ok&=np.linalg.norm(delta-t[:,None]*axis,axis=1)>1.2
  for offset in [np.zeros(3),*dirs]:
   ids=np.flatnonzero(ok)
   if not len(ids):break
   ok[ids]&=~np.any([m.contains(points[ids]+offset)for m in meshes],axis=0)
  return ok
 def dense(points,spacing=.07):return np.concatenate([a+(b-a)*np.linspace(0,1,max(2,int(np.linalg.norm(b-a)/spacing)+1))[:,None]for a,b in zip(points,points[1:])])
 lo=np.array([-15.,-3.,-19.]);hi=np.array([7.,5.,3.]);step=.2;shape=np.ceil((hi-lo)/step).astype(int)+1;idx=np.indices(shape).reshape(3,-1).T;grid=((lo+idx*step)@basis+origin).reshape(*shape,3);valid=free(grid.reshape(-1,3)).reshape(shape);print(key,'grid',shape,'valid',valid.sum(),flush=True)
 neighbors=[np.array(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)];result=[]
 for j,kind in enumerate(['PP-ext','PP-flex']):
  start=origin+basis[0]*(.45 if j==0 else -.45);end=np.array(P[key]['ppExits']['Index'][kind]);print('seeds',key,kind,free([start,end]),flush=True)
  assert free([start])[0],('start blocked',key,kind)
  if not free([end])[0]:
   candidates=np.array([end+d*radius for radius in [.1,.2,.3,.4,.5] for d in dirs/.18]);good=candidates[free(candidates)];assert len(good),('exit blocked',key,kind);adjusted=good[np.argmin(np.linalg.norm(good-end,axis=1))];print('exit correction',np.linalg.norm(adjusted-end),flush=True);end=adjusted
  inds=np.argwhere(valid);world=grid[valid]
  def seed(target):
   for ii in np.argsort(np.linalg.norm(world-target,axis=1))[:100]:
    if free(dense([target,world[ii]])).all():return tuple(inds[ii])
   raise ValueError('no seed')
  a,b=seed(start),seed(end);queue=[(0,0,a)];cost={a:0};back={};dest=np.array(b)
  while queue:
   _,g,node=heapq.heappop(queue)
   if g!=cost[node]:continue
   if node==b:break
   n=np.array(node)
   for off in neighbors:
    nxt=n+off;t=tuple(nxt)
    if np.any(nxt<0)or np.any(nxt>=shape)or not valid[t]:continue
    if any(not valid[tuple(n+np.eye(3,dtype=int)[i]*off[i])]for i in range(3)if off[i]):continue
    ng=g+np.linalg.norm(off)
    if ng<cost.get(t,float('inf')):cost[t]=ng;back[t]=node;heapq.heappush(queue,(ng+np.linalg.norm(nxt-dest),ng,t))
  assert b in cost,('no path',key,kind);chain=[b];node=b
  while node!=a:node=back[node];chain.append(node)
  path=np.array([start,*[grid[i]for i in reversed(chain)],end]);simple=[path[0]];i=0
  while i<len(path)-1:
   j=min(len(path)-1,i+15)
   while j>i+1 and not free(dense([path[i],path[j]])).all():j-=1
   simple.append(path[j]);i=j
  path=dense(np.array(simple),.12);assert free(dense(path,.04)).all();result.append(path.round(5).tolist());print(key,kind,'route',len(path),flush=True)
  others=np.concatenate([others,path]);tree=cKDTree(others);valid&=(tree.query(grid.reshape(-1,3))[0]>.36).reshape(shape)
 out[key]={'paths':result,'housing':origin.round(5).tolist(),'opening':(-basis[1]).round(8).tolist()};args.output.write_text(json.dumps(out,separators=(',',':'))+'\n')

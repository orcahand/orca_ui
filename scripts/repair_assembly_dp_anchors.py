"""Align the Touch flex-tendon illustration with the actual DP knot housing."""
from pathlib import Path
import json,heapq,itertools
import numpy as np,cadquery as cq,trimesh
from scipy.spatial import cKDTree
from cad_render_mesh import render_mesh
import argparse
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Route the Touch DP flex tendon from the shared knot housing; write a staging file.')
parser.add_argument('--touch-breps',type=Path,required=True)
parser.add_argument('--input',type=Path,default=ROOT/'frontend/src/components/assembly/channelRoutes.json')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
routes=json.loads(args.input.read_text());frames=json.loads((ROOT/'frontend/src/components/assembly/jointFrames.json').read_text())
for key in ['touch-right','touch-left']:
 solid=cq.Shape.importBrep(str(args.touch_breps/(key+'-Index-DP.brep')));mesh=render_mesh(solid,.03,.1);mesh.ray=trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
 pp=cq.Shape.importBrep(str(args.touch_breps/(key+'-Index-PP.brep')));ppmesh=render_mesh(pp,.03,.1);ppmesh.ray=trimesh.ray.ray_pyembree.RayMeshIntersector(ppmesh)
 paths=routes[key]['p33'];other=np.array(paths[1]['moving']);origin=other[0];basis=np.array([frames[key]['Index'][a]for a in ['x','y','z']]);tree=cKDTree(other)
 dirs=np.array([np.array(p)/np.linalg.norm(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)])*.18
 def free(points):
  points=np.asarray(points).reshape(-1,3);good=tree.query(points)[0]>.38
  for offset in [np.zeros(3),*dirs]:
   ids=np.flatnonzero(good)
   good[ids]&=~mesh.contains(points[ids]+offset)&~ppmesh.contains(points[ids]+offset)
  return good
 def dense(points,spacing=.06):return np.concatenate([a+(b-a)*np.linspace(0,1,max(2,int(np.linalg.norm(b-a)/spacing)+1))[:,None]for a,b in zip(points,points[1:])])
 lo=np.array([-14.,-2.5,-13.]);hi=np.array([5.,3.,5.]);step=.2;axes=[np.arange(a,b+step,step)for a,b in zip(lo,hi)];shape=tuple(map(len,axes));grid=np.stack(np.meshgrid(*axes,indexing='ij'),-1)@basis+origin
 valid=free(grid.reshape(-1,3)).reshape(shape);print(key,'grid',shape,'free',valid.sum(),flush=True)
 old=np.array(paths[0]['moving']);local=(old-origin)@basis.T;endidx=np.flatnonzero(local[:,2]<-10)[0];end=old[endidx]
 inds=np.argwhere(valid);world=grid[valid]
 def seed(target):
  for ix in np.argsort(np.linalg.norm(world-target,axis=1))[:100]:
   if free(dense([target,world[ix]])).all():return tuple(inds[ix])
  raise ValueError(('No seed',target))
 start=origin+np.array([-.6,1.3,0])@basis
 assert free([start])[0],start
 a,b=seed(start),seed(end);neighbor=[np.array(p)for p in itertools.product([-1,0,1],repeat=3)if any(p)];queue=[(0,0,a)];cost={a:0};back={};dest=np.array(b);nvisited=0
 while queue:
  _,g,node=heapq.heappop(queue)
  if g!=cost[node]:continue
  if node==b:break
  nvisited+=1;n=np.array(node)
  for off in neighbor:
   nxt=n+off;t=tuple(nxt)
   if np.any(nxt<0)or np.any(nxt>=shape)or not valid[t]:continue
   if any(not valid[tuple(n+np.eye(3,dtype=int)[i]*off[i])]for i in range(3)if off[i]):continue
   ng=g+np.linalg.norm(off)
   if ng<cost.get(t,float('inf')):cost[t]=ng;back[t]=node;heapq.heappush(queue,(ng+np.linalg.norm(nxt-dest),ng,t))
 assert b in cost,'no path'
 chain=[b];node=b
 while node!=a:node=back[node];chain.append(node)
 pts=np.array([start,*[grid[i]for i in reversed(chain)],end]);simplified=[pts[0]];i=0
 while i<len(pts)-1:
  j=min(len(pts)-1,i+15)
  while j>i+1 and not free(dense([pts[i],pts[j]])).all():j-=1
  simplified.append(pts[j]);i=j
 repaired=dense(np.array(simplified),.12);assert free(dense(repaired,.04)).all()
 paths[0]['moving']=np.concatenate([repaired,old[endidx+1:]]).round(5).tolist()
 print(key,'repair points',len(repaired),'start',start,'visited',nvisited,flush=True)
args.output.write_text(json.dumps(routes,separators=(',',':'))+'\n')

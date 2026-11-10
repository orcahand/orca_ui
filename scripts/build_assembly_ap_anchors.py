"""Extract AP tendon-anchor centerlines independently of the four PTFE channels."""
from pathlib import Path
import json,argparse,numpy as np,cadquery as cq,trimesh
from scipy.ndimage import label,center_of_mass
from OCP.BRepAdaptor import BRepAdaptor_Surface
from cad_render_mesh import render_mesh
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Extract the two curved AP anchor holes from STEP cross-sections.')
parser.add_argument('--base-breps',type=Path,required=True)
parser.add_argument('--touch-breps',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
F=json.load(open(ROOT/'frontend/src/components/assembly/jointFrames.json'));out={}
for key in F:
 root=args.touch_breps if key.startswith('touch')else args.base_breps;solid=cq.Shape.importBrep(str(root/(key+'-Index-AP.brep')));mesh=render_mesh(solid,.03,.1);mesh.ray=trimesh.ray.ray_pyembree.RayMeshIntersector(mesh);frame=F[key]['Index'];basis=np.array([frame[a]for a in ['x','y','z']]);origin=np.array(frame['origin']);pincenters=[]
 for face in solid.Faces():
  ad=BRepAdaptor_Surface(face.wrapped)
  if str(ad.GetType()).endswith('Cylinder')and abs(ad.Cylinder().Radius()-1.1)<.001 and ad.LastUParameter()-ad.FirstUParameter()>6:pincenters.append((np.array(face.Center().toTuple())-origin)@basis.T)
 assert len(pincenters)==4;mid=np.mean(pincenters,axis=0)[1];x=np.arange(-.5,3.6,.05);z=np.arange(-18,-8,.05);xx,zz=np.meshgrid(x,z,indexing='ij');paths=[]
 for side in [-1,1]:
  path=[]
  for distance in np.arange(9,1.99,-.1):
   y=mid+side*distance;pts=np.stack([xx,np.full_like(xx,y),zz],-1)@basis+origin;inside=mesh.contains(pts.reshape(-1,3)).reshape(xx.shape);labs,n=label(~inside);edge=set(labs[0])|set(labs[-1])|set(labs[:,0])|set(labs[:,-1]);candidates=[]
   for i in range(1,n+1):
    count=(labs==i).sum()
    if i in edge or not 50<count<1200:continue
    cx,cz=center_of_mass(labs==i);p=np.array([x[0]+cx*.05,y,z[0]+cz*.05]);candidates.append(p)
   if candidates:
    target=path[-1]if path else np.array([1.5,y,-15]);p=min(candidates,key=lambda p:np.linalg.norm(p-target));path.append(p)
   elif len(path)>8:break
  assert len(path)>20,(key,side,len(path));p=np.array(path);world=p@basis+origin
  # Continue along each mouth tangent only while remaining in open air.
  tangent=world[-1]-world[-3];tangent/=np.linalg.norm(tangent);end=world[-1]+tangent*.6
  tangent0=world[0]-world[2];tangent0/=np.linalg.norm(tangent0);start=world[0]+tangent0*1.0
  world=np.array([start,*world,end]);print(key,side,'samples',len(world),'local ends',np.round((world[[0,-1]]-origin)@basis.T,3),flush=True);paths.append(world.round(5).tolist())
 out[key]={'paths':paths,'up':basis[2].round(8).tolist(),'across':basis[1].round(8).tolist(),'front':basis[0].round(8).tolist()}
 args.output.write_text(json.dumps(out,separators=(',',':'))+'\n')

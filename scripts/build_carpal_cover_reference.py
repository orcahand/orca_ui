"""Package the separate Touch carpal bodies for the cover fitting illustration.

The full assembly's carpal mesh includes geometry overlapping the separate cover.
Use the matching printable bodies instead. Preserves STL triangle positions, indexes shared vertices and computes smooth
normals for the illustration. Requires NumPy.
"""
import argparse,json,struct,hashlib
from pathlib import Path
import numpy as np
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path,help='Touch 02_Carpals directory')
args=parser.parse_args()
out=Path(__file__).resolve().parents[1]/'frontend/public/assembly/details'
metadata={}
for side,letter in [('right','R'),('left','L')]:
 source=args.source/f'Carpals-{letter}-Touch.stl';raw=source.read_bytes();count=struct.unpack_from('<I',raw,80)[0]
 triangles=np.ndarray(count,dtype=np.dtype([('normal','<f4',3),('vertices','<f4',(3,3)),('attr','<u2')]),buffer=raw,offset=84)
 positions,indices=np.unique(triangles['vertices'].reshape(-1,3),axis=0,return_inverse=True)
 positions=positions.astype('<f4');indices=indices.astype('<u4')
 faces=positions[indices.reshape(-1,3)]
 face_normals=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
 normals=np.zeros_like(positions)
 np.add.at(normals,indices,np.repeat(face_normals,3,axis=0))
 normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
 chunks=[positions.tobytes(),normals.tobytes(),indices.tobytes()];offset=0;views=[]
 for i,data in enumerate(chunks):views.append({'buffer':0,'byteOffset':offset,'byteLength':len(data),'target':34963 if i==2 else 34962});offset+=len(data)
 gltf={'asset':{'version':'2.0','generator':'ORCA carpal cover reference'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'name':'Touch carpals','mesh':0}],'meshes':[{'primitives':[{'attributes':{'POSITION':0,'NORMAL':1},'indices':2}]}],'buffers':[{'byteLength':offset}],'bufferViews':views,'accessors':[{'bufferView':0,'componentType':5126,'count':len(positions),'type':'VEC3','min':positions.min(0).tolist(),'max':positions.max(0).tolist()},{'bufferView':1,'componentType':5126,'count':len(normals),'type':'VEC3'},{'bufferView':2,'componentType':5125,'count':len(indices),'type':'SCALAR'}]}
 encoded=json.dumps(gltf,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4);binary=b''.join(chunks)
 result=struct.pack('<III',0x46546c67,2,28+len(encoded)+len(binary))+struct.pack('<I4s',len(encoded),b'JSON')+encoded+struct.pack('<I4s',len(binary),b'BIN\0')+binary
 (out/f'touch-carpals-{side}.glb').write_bytes(result)
 metadata[side]={'source':source.name,'sha256':hashlib.sha256(raw).hexdigest(),'triangles':count,'vertices':len(positions),'cover':f'carpal-cover-{side}.stl','coverSource':f'Coav-{letter}.stl'}
 print(side,count,'triangles',len(result),'bytes')
(out/'carpal-cover-sources.json').write_text(json.dumps(metadata,indent=2)+'\n')

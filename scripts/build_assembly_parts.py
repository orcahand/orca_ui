#!/usr/bin/env python3
"""Convert complete STEP assemblies into per-component GLBs and illustrated inventories.

Run in a tooling environment with cadquery, trimesh, numpy and pillow installed.
Original archives are read-only. Coincident repeated CAD occurrences are removed;
purchased motors and populated PCBs are kept as buildable units.
"""
import argparse, collections, hashlib, json, re, time
from pathlib import Path
import cadquery as cq
from cad_render_mesh import render_mesh
import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
GROUPS=['Fingers','Thumb','Carpals','Wrist & tower','Skins','Drive & electronics','Standard components','Tendons']

def clean(name):
    return re.sub(r'\s*\(\d+\)','',re.sub(r':\d+$','',name)).replace('(Mirror)','').strip()

def title(name,path,finger_map=None):
    if name.startswith('=>'):name=clean(path.split('/')[-2])
    branch=path.split('/')[2].replace('-Touch','') if len(path.split('/'))>2 else ''
    finger=(finger_map or {}).get(branch) or ('Index' if branch in ['I-R','I-L'] else 'Middle' if branch=='M' else 'Ring' if branch=='M (1)' else 'Pinky' if branch=='P' else None)
    if finger and re.match(r'[IMP]-(AP|IP|PP)',name):
        segment='DP' if '-IP' in name else 'PP' if '-PP' in name else 'AP'
        return f'{finger} {segment}'
    if name=='Skin':
        for token in reversed(path.split('/')[:-1]):
            if re.match(r'[IMPT]-(PP|DP)',clean(token)):return (f'{finger} PP' if finger else clean(token))+' skin'
        return 'Palm skin'
    names={'4x8x3':'Bearing · 4 × 8 × 3','CORE':'Carpal core','Male':'Wrist pulley','Ratchet_Main':'Top spool / tensioner','orcahand':'Spool ORCA insert','FanCover_Feetech_TwoFans':'Fan cover · two fans','90591A265_Zinc-Plated Steel Hex Nut':'M2 hex nut','OH_PCB':'OH control board','XC-330':'Dynamixel XC330 motor','XC-430':'Dynamixel XC430 wrist motor','PCB-Connector':'Motor connector PCB','Magnet-WithPoles':'Hull magnet','Magnet-5x3':'Magnet · 5 × 3 mm','FrankaConnector':'Arm mounting adapter','ThreadedRod':'Arm mounting rod','Tendons':'Tendon cord','SidePlate-Touch':'Side plate','SpoolHolder_CNC':'Metal spool holder','Conn_board_touch':'Touch connector board','Conn_board_only_Tactile':'Touch connector board'}
    if name in names:return names[name]
    match=re.search(r'Head Cap Screw.*? - M([\d.]+) x [\d.]+ x ([\d.]+)',name)
    if match:return f'M{match[1]} × {match[2]} socket screw'
    match=re.search(r'Hexagon Nut.*? - M([\d.]+)',name)
    if match:return f'M{match[1]} hex nut'
    return name.replace('bearing_','Bearing · ').replace('Pin-','Pin · ').replace('_',' ').replace('x',' × ') if name.startswith(('bearing_','Pin-')) else name.replace('_',' ')

def display_label(label):
    names={
        'R-T-AP':'Thumb AP', 'T-DP':'Thumb DP', 'T-PP':'Thumb PP',
        'T-TP-R':'Thumb TP', 'T-TP-L':'Thumb TP', 'T-PP skin':'Thumb PP skin',
        'T-DP-Touch skin':'Thumb DP skin', 'I-R-DP-Skin':'Index DP skin',
        'I-L-DP-Skin':'Index DP skin', 'M-DP-Skin':'Middle / ring DP skin',
        'P-DP-Skin':'Pinky DP skin', 'P-Touch-DP-Skin':'Pinky touch skin',
        'R-Carpals':'Carpals', 'L-Carpals':'Carpals', 'Carpals-R-Touch':'Touch carpals',
        'CarpalsTeeth':'Carpal pulley', 'ForeArmStructure Dynamixel':'Motor tower',
        'WristAdaper Dynamixel':'Wrist motor adapter', 'WristStructure Dynamixel':'Wrist frame',
        'GT2-142-Belt':'GT2 belt · 142 mm', 'HullFront':'Hull cover', 'HullBack':'Rear hull cover',
        'BaseSpool':'Bottom spool', 'SpoolCover':'Spool cover', 'CoolingFan':'Cooling fan',
        'M4-Square-Nut':'M4 square nut', 'M4-Washer':'M4 washer',
        'Arm mounting adapter':'Arm mounting adapter (optional)',
        'Arm mounting rod':'Arm mounting rod (optional)', 'Tendon cord':'Tendon paths',
        'ORCA SENSOR M':'Middle / ring / index touch module',
        'ORCA SENSOR P':'Pinky touch module', 'ORCA SENSOR T':'Thumb touch module',
        'Touch connector board':'Touch connector board',
    }
    if label in names:return names[label]
    match=re.search(r'Cheese Head Screw .*? - M([\d.]+) x (?:[\d.]+ x )?([\d.]+)',label)
    if match:return f'M{match[1]} × {match[2]} cheese-head screw'
    return label

def category(name,path):
    text=(name+' '+path).lower()
    if 'tendon' in text:return 'Tendons'
    if any(t in name.lower() for t in ['skin']):return 'Skins'
    if any(t in name.lower() for t in ['bearing','pin-','pin ·','screw','nut','washer','magnet','threadedrod']):return 'Standard components'
    if any(t in name for t in ['XC-330','XC-430','HLS','OH_PCB','PCB-Connector','CoolingFan','ORCA_SENSOR','ConnectorBoard','Conn_board_touch','Conn_board_only_Tactile']):return 'Drive & electronics'
    if any(t in text for t in ['thumb','/t-','/r-t-','/l-t-']):return 'Thumb'
    if any(t in text for t in ['/i-r','/i-l','/m/','/m (','/p/','/p (','/m-touch','/p-touch']):return 'Fingers'
    if any(t in text for t in ['carpal','/core']):return 'Carpals'
    if any(t in text for t in ['spool','ratchet']):return 'Drive & electronics'
    return 'Wrist & tower'

def assembly_area(path):
    branch=path.split('/')[2].lower() if len(path.split('/'))>2 else ''
    if 'tendon' in branch:return 'Routing'
    if 'thumb' in branch:return 'Thumb'
    if branch.startswith(('i-r','i-l','m-touch','p-touch')) or branch in ['m','m (1)','p']:return 'Fingers'
    if 'carpal' in branch:return 'Carpals'
    if 'wrist' in branch:return 'Wrist'
    if any(token in branch for token in ['tower','hull','plate','franka','threadedrod']):return 'Tower'
    return None

def thumb(mesh,path,color):
    verts=mesh.vertices.copy();verts-=mesh.bounds.mean(axis=0)
    # Fixed isometric view, with a stable PCA orientation for narrow hardware.
    if np.ptp(verts,axis=0).max()/max(np.ptp(verts,axis=0).min(),.1)>5:
        _,_,axes=np.linalg.svd(verts,full_matrices=False);verts=verts@axes.T
    ax=.55;ay=-.65
    rx=np.array([[1,0,0],[0,np.cos(ax),-np.sin(ax)],[0,np.sin(ax),np.cos(ax)]])
    ry=np.array([[np.cos(ay),0,np.sin(ay)],[0,1,0],[-np.sin(ay),0,np.cos(ay)]])
    v=verts@ry.T@rx.T;v*=150/max(np.ptp(v[:,:2],axis=0).max(),.01)
    xy=np.column_stack([v[:,0]+110,90-v[:,1]])
    faces=mesh.faces
    normal=np.cross(v[faces[:,1]]-v[faces[:,0]],v[faces[:,2]]-v[faces[:,0]])
    normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-9)
    light=np.clip(normal@np.array([-.3,.6,.74]),0,1)*.4+.6
    im=Image.new('RGBA',(220,180),(0,0,0,0));draw=ImageDraw.Draw(im)
    for i in np.argsort(v[faces,2].mean(axis=1)):
        c=tuple(int(np.clip(val*light[i],0,255)) for val in color[:3])+(255,)
        draw.polygon([tuple(x) for x in xy[faces[i]]],fill=c)
    im.save(path)

def build(source,out,key,brep_dir=None):
    t=time.time();print('Read',source.name,flush=True)
    assy=cq.Assembly.load(str(source))
    atoms=[];motor_positions=set()
    def walk(node,loc=cq.Location(),path=''):
        loc=loc*node.loc;path+='/'+node.name
        name=clean(node.name)
        if name=='XC-330-MotorAssembly':
            def motor_center(n,l):
                l=l*n.loc
                if n.obj is not None and 'DC15_A01_CASE_M' in n.name and n.obj.Faces():
                    return tuple(round(x,2) for x in n.obj.moved(l).BoundingBox().center.toTuple())
                for c in n.children:
                    result=motor_center(c,l)
                    if result is not None:return result
            position=motor_center(node,loc*node.loc.inverse)
            if position is not None:
                if position in motor_positions:return
                motor_positions.add(position)
        atomic=name in ['XC-330','XC-430','OH_PCB','Conn_board_touch','Conn_board_only_Tactile'] or name.startswith('ORCA_SENSOR')
        if atomic:
            shape=node.toCompound().moved(loc*node.loc.inverse)
            if shape.Faces():atoms.append((name,path,shape,node.color))
            return
        if node.obj is not None and node.obj.Faces():
            actual=clean(path.split('/')[-2]) if name.startswith('=>') else name
            shape=node.obj.moved(loc)
            if actual=='Tendons':
                for solid in shape.Solids():atoms.append((actual,path,solid,node.color))
            else:atoms.append((actual,path,shape,node.color))
        for child in node.children:walk(child,loc,path)
    walk(assy)
    # Repeated M assemblies are not ordered consistently between STEP exports.
    ap_positions={}
    for name,path,shape,_ in atoms:
        branch=path.split('/')[2].replace('-Touch','')
        if re.match(r'[IMP]-AP',name) and branch in ['I-R','I-L','M','M (1)']:
            ap_positions[branch]=np.array(shape.BoundingBox().center.toTuple())
    index=next(value for branch,value in ap_positions.items() if branch in ['I-R','I-L'])
    middle,ring=sorted(['M','M (1)'],key=lambda branch:np.linalg.norm(ap_positions[branch]-index))
    finger_map={middle:'Middle',ring:'Ring'}
    print('Atoms',len(atoms),flush=True)
    out.mkdir(parents=True,exist_ok=True)
    scene=trimesh.Scene();geometry_cache={};parts={};seen=set();rejected=0;bounds=[];totaltri=0
    anchors=[]
    for name,path,shape,color in atoms:
        area=assembly_area(path)
        if area and area!='Routing':
            box=shape.BoundingBox();anchors.append((area,np.array([[box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax]])))
    for name,path,shape,color in atoms:
        box=shape.BoundingBox();bb=np.array([[box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax]])
        # Same component type and same occupied box identifies coincident export duplicates.
        identity=(name,tuple(np.round(bb.flatten(),2)))
        if identity in seen:rejected+=1;continue
        seen.add(identity)
        label=title(name,path,finger_map);cat=category(name,path)
        if name=='4x8x3':cat='Standard components'
        if name=='Tendons':cat='Tendons'
        if re.match(r'^(Index|Middle|Ring|Pinky) (AP|DP|PP)$',label):cat='Fingers'
        # Separate skins and finger parts named identically inside different assemblies.
        group_key=label
        if label in ['Palm skin','CORE'] and cat!='Carpals':group_key=label+cat
        pid=hashlib.sha1(group_key.encode()).hexdigest()[:10]
        part=parts.setdefault(pid,{'id':pid,'label':display_label(label),'category':cat,'count':0,'nodes':[],'areas':{},'thumbnail':f'./assembly/parts/{key}/{pid}.png'})
        if brep_dir is not None and re.match(r'^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$|^(Carpals|Touch carpals|Carpal core|Wrist frame)$',part['label']):
            brep_dir.mkdir(parents=True,exist_ok=True)
            shape.exportBrep(str(brep_dir/f"{key.removesuffix('-dynamixel')}-{part['label'].replace(' ','-')}.brep"))
        mesh=render_mesh(shape,.1 if name in ['XC-330','XC-430'] else .06)
        if not len(mesh.faces):continue
        center=mesh.bounds.mean(axis=0)
        mesh.apply_translation(-center)
        faces=mesh.faces
        totaltri+=len(faces)
        if cat=='Tendons':rgb=[59,156,162]
        elif cat=='Standard components':rgb=[158,168,180]
        elif cat=='Skins':rgb=[228,232,232] if key.startswith('base') else [68,73,79]
        elif name=='OH_PCB':rgb=[23,28,27]
        elif cat=='Drive & electronics':rgb=[62,85,99] if 'PCB' not in name else [42,111,101]
        else:rgb=[77,86,95]
        mesh.visual=trimesh.visual.ColorVisuals(mesh,vertex_colors=rgb+[255])
        nid=f'piece_{len(bounds):04d}';matrix=np.eye(4);matrix[:3,3]=center
        signature=hashlib.sha1(np.round(mesh.vertices,5).tobytes()+mesh.faces.tobytes()+bytes(rgb)).hexdigest()
        if signature in geometry_cache:
            scene.graph.update(frame_to=nid,matrix=matrix,geometry=geometry_cache[signature])
        else:
            scene.add_geometry(mesh,node_name=nid,geom_name=nid,transform=matrix)
            geometry_cache[signature]=nid
        part['nodes'].append(nid);part['count']+=1;bounds.append(bb)
        area=assembly_area(path)
        if area is None:
            area=min(anchors,key=lambda a:np.linalg.norm(np.maximum(a[1][0]-center,0)+np.maximum(center-a[1][1],0)))[0]
        part['areas'].setdefault(area,[]).append(nid)
        if part['count']==1 and not (out/f'{pid}.png').exists():thumb(mesh,out/f'{pid}.png',rgb)
    data={'key':key,'parts':sorted(parts.values(),key=lambda p:(GROUPS.index(p['category']),p['label'])),'bounds':[np.min(np.array(bounds)[:,0],axis=0).tolist(),np.max(np.array(bounds)[:,1],axis=0).tolist()],'instanceCount':len(bounds),'duplicatesRemoved':rejected}
    data['source']={'file':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    scene.export(out/'assembly.glb',include_normals=True)
    (out/'inventory.json').write_text(json.dumps(data,indent=2)+'\n')
    print('DONE',key,len(parts),'types',len(bounds),'instances',rejected,'duplicates',totaltri,'triangles',round(time.time()-t),'s',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('key');p.add_argument('--out',type=Path);p.add_argument('--brep-dir',type=Path);a=p.parse_args()
    build(a.source,a.out or ROOT/'frontend/public/assembly/parts'/a.key,a.key,a.brep_dir)

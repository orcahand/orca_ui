"""Export a small, component-colored Touch board detail from the complete STEP.

Usage: python scripts/build_touch_board_detail.py /path/to/TouchV2_Assembly_Right.step
The geometry stays in assembly coordinates; the guide can position it for either hand.
"""
import argparse, hashlib, json
from pathlib import Path
import cadquery as cq
import trimesh
from cad_render_mesh import render_mesh

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    args=parser.parse_args()
    inventory=json.loads((ROOT/'frontend/public/assembly/parts/touch-right-dynamixel/inventory.json').read_text())
    digest=hashlib.sha256(args.source.read_bytes()).hexdigest()
    assert digest==inventory['source']['sha256'], 'Use the STEP matching the guide model.'
    assembly=cq.Assembly.load(str(args.source))
    scene=trimesh.Scene();components=[]
    def walk(node,location=cq.Location(),path=''):
        location=location*node.loc;path+='/'+node.name
        if '/Conn_board_touch/' in path and node.obj is not None and node.obj.Faces():
            mesh=render_mesh(node.obj.moved(location),tolerance=.025,angle=.1)
            socket='CONN-TH_A2001WR-4P' in path
            color=[235,235,226,255] if socket else [95,101,104,255] if '/C3~' in path or '/C4~' in path else [25,30,29,255]
            mesh.visual=trimesh.visual.ColorVisuals(mesh,vertex_colors=color)
            name='Board cable socket' if socket else 'PCB' if '/Board~' in path else node.name
            scene.add_geometry(mesh,node_name=name,geom_name=name)
            components.append({'name':name,'path':path,'bounds':mesh.bounds.tolist()})
        for child in node.children:walk(child,location,path)
    walk(assembly)
    assert len(components)==12
    output=ROOT/'frontend/public/assembly/details';output.mkdir(exist_ok=True)
    scene.export(output/'touch-connector-board.glb')
    (output/'touch-connector-board.json').write_text(json.dumps({'sourceSha256':digest,'components':components},indent=2)+'\n')
    print('Exported Touch board detail:',(output/'touch-connector-board.glb').stat().st_size,'bytes',flush=True)

if __name__=='__main__':main()

"""Preserve individual OH-board component colors from the current complete STEP.

Write to a staging folder; the board remains one inventory item and one GLB node.
"""
import argparse, hashlib, json
from pathlib import Path
import cadquery as cq
import numpy as np
from build_assembly_parts import clean
from cad_render_mesh import render_mesh
from refine_assembly_meshes import read_glb, write_glb

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('key', choices=[f'{v}-{s}-dynamixel' for v in ['base', 'touch'] for s in ['left', 'right']])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    folder = ROOT/'frontend/public/assembly/parts'/args.key
    inventory = json.loads((folder/'inventory.json').read_text())
    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    assert inventory['source']['sha256'] == digest, 'STEP differs from the loaded assembly'
    assembly = cq.Assembly.load(str(args.source))
    meshes, colors, components = [], [], []

    def walk(node, location=cq.Location(), path='', board=False, color=None):
        location = location*node.loc
        path += '/'+node.name
        board = board or clean(node.name) == 'OH_PCB'
        color = node.color or color
        if board and node.obj is not None and node.obj.Faces():
            shape = node.obj.moved(location)
            mesh = render_mesh(shape)
            rgb = np.array(color.toTuple()[:3] if color else [.71, .74, .76])
            if clean(node.name) == 'OH_PCB_PCB':
                rgb = np.array([23, 28, 27])/255
            linear = np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
            meshes.append(mesh)
            colors.append(np.tile(linear, (len(mesh.vertices), 1)))
            components.append(dict(path=path, color=rgb.tolist(), vertices=len(mesh.vertices), bounds=mesh.bounds.tolist()))
        for child in node.children:
            walk(child, location, path, board, color)

    walk(assembly)
    assert meshes, 'No OH board in STEP'
    part = next(p for p in inventory['parts'] if p['label'] == 'OH control board')
    assert len(part['nodes']) == 1
    doc, binary = read_glb(folder/'assembly.glb')
    node = next(n for n in doc['nodes'] if n.get('name') == part['nodes'][0])
    matrix = np.array(node.get('matrix', np.eye(4).flatten())).reshape(4, 4).T
    assert np.allclose(matrix[:3, :3], np.eye(3))
    positions = np.concatenate([m.vertices for m in meshes])-matrix[:3, 3]
    normals = np.concatenate([m.vertex_normals for m in meshes])
    offsets = np.cumsum([0]+[len(m.vertices) for m in meshes])
    indices = np.concatenate([m.faces+offset for m, offset in zip(meshes, offsets)]).flatten()
    old = doc['meshes'][node['mesh']]['primitives'][0]
    bounds = doc['accessors'][old['attributes']['POSITION']]
    delta = max(abs(positions.min(axis=0)-bounds['min']).max(), abs(positions.max(axis=0)-bounds['max']).max())
    assert delta < .1, ('Board placement differs from assembly', delta)

    def attribute(array, kind, dtype, component, target):
        array = np.asarray(array, dtype=dtype)
        binary.extend(b'\0'*((-len(binary)) % 4))
        doc['bufferViews'].append(dict(buffer=0, byteOffset=len(binary), byteLength=array.nbytes, target=target))
        binary.extend(array.tobytes())
        accessor = dict(bufferView=len(doc['bufferViews'])-1, componentType=component, count=len(array), type=kind)
        if kind == 'VEC3':
            accessor.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
        doc['accessors'].append(accessor)
        return len(doc['accessors'])-1

    primitive = dict(attributes={
        'POSITION': attribute(positions, 'VEC3', '<f4', 5126, 34962),
        'NORMAL': attribute(normals, 'VEC3', '<f4', 5126, 34962),
        'COLOR_0': attribute(np.concatenate(colors), 'VEC3', '<f4', 5126, 34962),
    }, indices=attribute(indices, 'SCALAR', '<u4', 5125, 34963), mode=4)
    doc.setdefault('materials', []).append(dict(name='OH board components', pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], roughnessFactor=.48, metallicFactor=0)))
    primitive['material'] = len(doc['materials'])-1
    doc['meshes'][node['mesh']]['primitives'] = [primitive]
    args.output.mkdir(parents=True, exist_ok=True)
    write_glb(args.output/'assembly.glb', doc, binary)
    report = dict(key=args.key, sourceSha256=digest, node=part['nodes'][0], boundsDifference=float(delta), components=components)
    (args.output/'board-components.json').write_text(json.dumps(report, indent=2)+'\n')
    print(args.key, len(components), 'board components; bounds difference', delta, flush=True)


if __name__ == '__main__':
    main()

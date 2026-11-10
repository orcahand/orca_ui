"""Refine STEP-derived BREP parts without changing node identities or transforms.

python scripts/refine_assembly_meshes.py --brep-dir /path/to/extracted/breps
BREPs use names such as base-right-Carpals.brep, in assembly coordinates.
"""
import argparse, json, shutil, struct, tempfile
from pathlib import Path
import cadquery as cq
import numpy as np
from cad_render_mesh import render_mesh

ROOT = Path(__file__).resolve().parents[1]


def read_glb(path):
    data = path.read_bytes()
    length = struct.unpack_from('<I', data, 12)[0]
    doc = json.loads(data[20:20+length])
    start = 20+length
    size = struct.unpack_from('<I', data, start)[0]
    return doc, bytearray(data[start+8:start+8+size])


def write_glb(path, doc, binary):
    used_accessors = set()
    for mesh in doc['meshes']:
        for p in mesh['primitives']:
            used_accessors.update(p['attributes'].values())
            if 'indices' in p:
                used_accessors.add(p['indices'])
    accessor_map = {old: new for new, old in enumerate(sorted(used_accessors))}
    accessors = [doc['accessors'][i] for i in sorted(used_accessors)]
    views = sorted({a['bufferView'] for a in accessors})
    view_map, new_views, packed = {}, [], bytearray()
    for old in views:
        view = doc['bufferViews'][old].copy()
        offset, length = view.get('byteOffset', 0), view['byteLength']
        packed.extend(b'\0'*((-len(packed)) % 4))
        view['byteOffset'] = len(packed)
        packed.extend(binary[offset:offset+length])
        view_map[old] = len(new_views)
        new_views.append(view)
    for accessor in accessors:
        accessor['bufferView'] = view_map[accessor['bufferView']]
    for mesh in doc['meshes']:
        for p in mesh['primitives']:
            p['attributes'] = {k: accessor_map[v] for k, v in p['attributes'].items()}
            if 'indices' in p:
                p['indices'] = accessor_map[p['indices']]
    doc['accessors'], doc['bufferViews'] = accessors, new_views
    doc['buffers'] = [{'byteLength': len(packed)}]
    encoded = json.dumps(doc, separators=(',', ':')).encode()
    encoded += b' '*((-len(encoded)) % 4)
    packed.extend(b'\0'*((-len(packed)) % 4))
    data = struct.pack('<III', 0x46546C67, 2, 28+len(encoded)+len(packed))
    data += struct.pack('<II', len(encoded), 0x4E4F534A)+encoded
    data += struct.pack('<II', len(packed), 0x004E4942)+packed
    path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--brep-dir', type=Path, required=True)
    parser.add_argument('--key')
    args = parser.parse_args()
    backup = Path(tempfile.mkdtemp(prefix='orca-before-surface-refinement-'))
    print('Backups:', backup, flush=True)
    for folder in sorted((ROOT/'frontend/public/assembly/parts').iterdir()):
        if not folder.is_dir() or (args.key and folder.name != args.key):
            continue
        prefix = folder.name.removesuffix('-dynamixel')
        inventory = json.loads((folder/'inventory.json').read_text())
        doc, binary = read_glb(folder/'assembly.glb')
        assert not doc.get('animations') and not doc.get('skins') and not doc.get('images')
        nodes = {n['name']: n for n in doc['nodes'] if 'name' in n}
        count = 0
        for part in inventory['parts']:
            brep = args.brep_dir/f"{prefix}-{part['label'].replace(' ', '-')}.brep"
            if not brep.exists():
                continue
            mesh = render_mesh(cq.Shape.importBrep(str(brep)))
            for name in part['nodes']:
                node = nodes[name]
                matrix = np.array(node.get('matrix', np.eye(4).flatten())).reshape(4, 4).T
                assert np.allclose(matrix[:3, :3], np.eye(3)), name
                positions = np.asarray(mesh.vertices-matrix[:3, 3], dtype='<f4')
                normals = np.asarray(mesh.vertex_normals, dtype='<f4')
                indices = np.asarray(mesh.faces, dtype='<u4').flatten()
                def attribute(array, kind, component, target):
                    binary.extend(b'\0'*((-len(binary)) % 4))
                    view = {'buffer': 0, 'byteOffset': len(binary), 'byteLength': array.nbytes, 'target': target}
                    binary.extend(array.tobytes())
                    doc['bufferViews'].append(view)
                    accessor = {'bufferView': len(doc['bufferViews'])-1, 'componentType': component, 'count': len(array), 'type': kind}
                    if kind == 'VEC3':
                        accessor.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
                    doc['accessors'].append(accessor)
                    return len(doc['accessors'])-1
                previous = doc['accessors'][doc['meshes'][node['mesh']]['primitives'][0]['attributes']['POSITION']]
                delta = max(abs(positions.min(axis=0)-previous['min']).max(), abs(positions.max(axis=0)-previous['max']).max())
                assert delta < .5, (name, 'BREP does not match this CAD instance', delta)
                primitive = {'attributes': {'POSITION': attribute(positions, 'VEC3', 5126, 34962), 'NORMAL': attribute(normals, 'VEC3', 5126, 34962)}, 'indices': attribute(indices, 'SCALAR', 5125, 34963), 'mode': 4}
                old = doc['meshes'][node['mesh']]['primitives'][0]
                if 'material' in old:
                    primitive['material'] = old['material']
                doc['meshes'][node['mesh']]['primitives'] = [primitive]
            count += 1
        if count:
            shutil.copy2(folder/'assembly.glb', backup/f'{folder.name}.glb')
            write_glb(folder/'assembly.glb', doc, binary)
        print(folder.name, count, 'parts refined', flush=True)


if __name__ == '__main__':
    main()

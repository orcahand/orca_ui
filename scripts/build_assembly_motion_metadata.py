#!/usr/bin/env python3
"""Record world-space centers, hardware axes and STEP bearing ownership for lessons.

Run with cadquery, trimesh and numpy installed. Pass the directory containing
Orcahand_{BaseV2,TouchV2}_{Right,Left}.step. Rebuild the assembly GLBs first.
"""
import argparse
import json
from pathlib import Path
import cadquery as cq
import numpy as np
import trimesh
from build_assembly_parts import clean, title, display_label

ROOT = Path(__file__).resolve().parents[1] / 'frontend'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step_directory', type=Path)
    parser.add_argument('--version', choices=['base','touch'])
    parser.add_argument('--parts-root', type=Path, default=ROOT/'public/assembly/parts')
    parser.add_argument('--source-pattern', help='STEP filename, with {side} replaced by Right or Left')
    parser.add_argument('--output', type=Path, default=ROOT/'src/components/assembly/cadGeometry.json')
    args = parser.parse_args()
    result = json.loads(args.output.read_text()) if args.output.exists() else {}
    for version in ([args.version] if args.version else ('base', 'touch')):
        for side in ('right', 'left'):
            key = f'{version}-{side}'
            directory = args.parts_root / f'{key}-dynamixel'
            inventory = json.loads((directory / 'inventory.json').read_text())
            scene = trimesh.load(directory / 'assembly.glb', force='scene')
            nodes = {}
            for part in inventory['parts']:
                for name in part['nodes']:
                    matrix, geometry = scene.graph[name]
                    mesh = scene.geometry[geometry].copy()
                    mesh.apply_transform(matrix)
                    data = {'center': mesh.bounds.mean(axis=0).round(4).tolist()}
                    if part['category'] == 'Standard components':
                        _, vectors = np.linalg.eigh(np.cov(mesh.vertices.T))
                        flat = any(word in part['label'] for word in ('Bearing', 'nut', 'washer'))
                        data['axis'] = vectors[:, 0 if flat else 2].round(5).tolist()
                    nodes[name] = data
            source = args.step_directory / f'Orcahand_{"BaseV2" if version == "base" else "TouchV2"}_{side.title()}.step'
            if args.source_pattern:source=args.step_directory/args.source_pattern.format(side=side.title())
            assembly = cq.Assembly.load(str(source))
            parts = {p['label']: p for p in inventory['parts']}

            def walk(node, location=cq.Location(), path=''):
                location = location * node.loc
                path += '/' + node.name
                if node.obj is not None and node.obj.Faces() and ('bearing' in path.lower() or '4x8x3' in path):
                    name = clean(path.split('/')[-2]) if clean(node.name).startswith('=>') else clean(node.name)
                    part = parts.get(display_label(title(name, path)))
                    if part:
                        center = np.array(node.obj.moved(location).BoundingBox().center.toTuple())
                        match = min(part['nodes'], key=lambda n: np.linalg.norm(center - nodes[n]['center']))
                        if np.linalg.norm(center - nodes[match]['center']) < 1:
                            nodes[match]['path'] = path
                for child in node.children:
                    walk(child, location, path)

            walk(assembly)
            result[key] = nodes
            print(key, len(nodes), flush=True)
    args.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')

if __name__ == '__main__':
    main()

"""Extract Touch sensor screw seats from cylindrical CAD surfaces in the GLBs.

Uses the DP's 0.8 mm radius clearance holes and their coaxial head recesses.
Screw lengths follow screws-fingers.png and screws-thumb.png, not the incomplete
fastener instances in the CAD export. Requires NumPy.
"""
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def surfaces(document, raw, node):
    def array(index):
        accessor = document['accessors'][index]
        view = document['bufferViews'][accessor['bufferView']]
        columns = {'SCALAR': 1, 'VEC3': 3}[accessor['type']]
        return np.frombuffer(raw, dtype={5126: '<f4', 5125: '<u4', 5123: '<u2'}[accessor['componentType']],
                             count=accessor['count'] * columns,
                             offset=view.get('byteOffset', 0) + accessor.get('byteOffset', 0)).reshape(-1, columns)
    primitive = document['meshes'][node['mesh']]['primitives'][0]
    vertices = array(primitive['attributes']['POSITION']).astype(float)
    normals = array(primitive['attributes']['NORMAL']).astype(float)
    faces = array(primitive['indices']).reshape(-1, 3)
    parents = list(range(len(vertices)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for face in faces:
        for i in face[1:]:
            parents[root(i)] = root(face[0])
    groups = {}
    for i in range(len(vertices)):
        groups.setdefault(root(i), []).append(i)
    # Each CAD face retains independent vertices and smooth surface normals.
    for indices in groups.values():
        if len(indices) < 40:
            continue
        points, normal = vertices[indices], normals[indices]
        values, vectors = np.linalg.eigh(normal.T @ normal)
        if values[0] > .001 or values[1] < 1:
            continue
        axis, basis = vectors[:, 0], vectors[:, 1:]
        uv = points @ basis
        coefficients = np.linalg.lstsq(np.c_[2 * uv, np.ones(len(uv))], (uv * uv).sum(1), rcond=None)[0]
        radius = np.sqrt(max(0, coefficients[2] + sum(coefficients[:2] ** 2)))
        error = np.max(np.abs(np.linalg.norm(uv - coefficients[:2], axis=1) - radius))
        inward = np.mean(np.sum((uv - coefficients[:2]) * (normal @ basis), axis=1)) < 0
        if error > .01 or not inward:
            continue
        center = basis @ coefficients[:2] + axis * (np.min(points @ axis) + np.max(points @ axis)) / 2
        center += np.array(node['matrix'][12:15])
        yield dict(center=center, axis=axis, radius=radius, depth=np.ptp(points @ axis))


def coaxial(a, b):
    delta = b['center'] - a['center']
    return abs(a['axis'] @ b['axis']) > .999 and np.linalg.norm(delta - a['axis'] * (delta @ a['axis'])) < .18


result = {}
for side in ['right', 'left']:
    folder = ROOT / f'frontend/public/assembly/parts/touch-{side}-dynamixel'
    blob = (folder / 'assembly.glb').read_bytes()
    size = struct.unpack_from('<I', blob, 12)[0]
    document, raw = json.loads(blob[20:20 + size]), blob[28 + size:]
    inventory = json.loads((folder / 'inventory.json').read_text())
    result[side] = {}
    for finger in ['Index', 'Middle', 'Ring', 'Pinky', 'Thumb']:
        part = next(p for p in inventory['parts'] if p['label'] == f'{finger} DP')
        node = next(n for n in document['nodes'] if n.get('name') == part['nodes'][0])
        cylinders = list(surfaces(document, raw, node))
        holes = []
        for surface in cylinders:
            if abs(surface['radius'] - .8) < .003 and not any(coaxial(surface, h) for h in holes):
                holes.append(surface)
        if len(holes) != 4:
            raise ValueError(f'{side} {finger}: expected 4 clearance holes, found {len(holes)}')
        seats = []
        for hole in holes:
            recesses = [s for s in cylinders if any(abs(s['radius'] - r) < .005 for r in [1.35, 1.5]) and coaxial(hole, s)]
            if not recesses:
                raise ValueError(f'{side} {finger}: missing head recess')
            recess = max(recesses, key=lambda s: abs((s['center'] - hole['center']) @ hole['axis']))
            outward = hole['axis'] * np.sign((recess['center'] - hole['center']) @ hole['axis'])
            # Seat is the inner end of the head recess, not the top of the screw.
            seat = recess['center'] - outward * recess['depth'] / 2
            seats.append(dict(position=seat, outward=outward, recessDepth=round(float(recess['depth']), 5)))
        for i, seat in enumerate(sorted(seats, key=lambda s: -s['position'][1])):
            location = 'tip' if i < 2 else 'lower'
            seat.update(location=location, length=(4 if i < 2 else 6) if finger == 'Thumb' else (3 if i < 2 else 4))
            for field in ['position', 'outward']:
                seat[field] = seat[field].round(5).tolist()
        result[side][finger] = seats
        print(f'{side} {finger}: 4 screw seats verified')
output = ROOT / 'frontend/src/components/assembly/touchScrewLocations.json'
output.write_text(json.dumps(result, indent=2) + '\n')

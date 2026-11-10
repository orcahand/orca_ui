"""Carry verified channel paths across a STEP update containing translated parts.

Reject changed surfaces: those require extracting and checking new channel paths.
Write to a staging directory, then review alongside the rebuilt CAD inventory.
"""
import argparse
import json
from pathlib import Path
import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]/'frontend/src/components/assembly'


def surface_samples(shape):
    points = []
    for face in shape.Faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        for u in np.linspace(surface.FirstUParameter(), surface.LastUParameter(), 5):
            for v in np.linspace(surface.FirstVParameter(), surface.LastVParameter(), 5):
                points.append(surface.Value(float(u), float(v)).Coord())
    return np.array(points)


def translation(old, new):
    a, b = cq.Shape.importBrep(str(old)), cq.Shape.importBrep(str(new))
    delta = np.array(b.BoundingBox().center.toTuple())-a.BoundingBox().center.toTuple()
    assert len(a.Faces()) == len(b.Faces()), f'Changed topology: {new.name}'
    assert abs(a.Volume()-b.Volume()) < 1e-5, f'Changed volume: {new.name}'
    assert abs(a.Area()-b.Area()) < 1e-5, f'Changed surface area: {new.name}'
    ac, bc = surface_samples(a)+delta, surface_samples(b)
    error = max(cKDTree(ac).query(bc)[0].max(), cKDTree(bc).query(ac)[0].max())
    assert error < 1e-5, f'Changed surfaces: {new.name}, {error} mm'
    return delta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-breps', type=Path, required=True)
    parser.add_argument('--new-breps', type=Path, required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    shifts = {}
    for new in args.new_breps.glob(f'{args.key}-*.brep'):
        shifts[new.stem[len(args.key)+1:].replace('-', ' ')] = translation(args.old_breps/new.name, new)
    def move(point, part):
        return (np.array(point)+shifts[part]).round(5).tolist()
    def path(points, part):
        return [move(p, part) for p in points]
    changes = {}
    for filename in ['conduitRoutes.json','connectorPorts.json','channelRoutes.json','jointFrames.json']:
        data = json.loads((ROOT/filename).read_text())
        current = data[args.key]
        if filename == 'conduitRoutes.json':
            current['carpals'] = [path(p, 'Touch carpals' if args.key.startswith('touch') else 'Carpals') for p in current['carpals']]
            current['wrist'] = [path(p, 'Wrist frame') for p in current['wrist']]
            for finger, routes in current['ap'].items():
                current['ap'][finger] = {kind:path(p, f'{finger} AP') for kind,p in routes.items()}
        elif filename == 'connectorPorts.json':
            for field, segment in [('apAnchors','AP'),('ppExits','PP')]:
                for finger, ports in current[field].items():
                    current[field][finger] = {kind:move(p, f'{finger} {segment}') for kind,p in ports.items()}
            current['tpExits'] = {kind:move(p,'Thumb TP') for kind,p in current['tpExits'].items()}
        elif filename == 'channelRoutes.json':
            for route in current['p33']:
                route['moving'] = path(route['moving'],'Index DP')
                route['fixed'] = path(route['fixed'],'Index PP')
        else:
            for finger, frame in current.items():
                frame['origin'] = move(frame['origin'],f'{finger} PP')
        changes[filename] = data
    args.output.mkdir(parents=True,exist_ok=True)
    for filename,data in changes.items():
        (args.output/filename).write_text(json.dumps(data,separators=(',',':'))+'\n')
    (args.output/'route-frame-changes.json').write_text(json.dumps({part:delta.tolist() for part,delta in shifts.items()},indent=2)+'\n')
    print(args.key, len(shifts), 'unchanged part surfaces verified; route coordinates updated')


if __name__ == '__main__':
    main()

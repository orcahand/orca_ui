"""Plan thumb AP anchor illustrations through the STEP pocket and narrow side slot."""
from pathlib import Path
import argparse, heapq, itertools, json
import numpy as np
import cadquery as cq
import trimesh
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from cad_render_mesh import render_mesh

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-breps', type=Path, required=True)
parser.add_argument('--touch-breps', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--config', action='append', choices=['base-right', 'base-left', 'touch-right', 'touch-left'])
args = parser.parse_args()
frames = json.loads((ROOT/'frontend/src/components/assembly/jointFrames.json').read_text())
result = json.loads(args.output.read_text()) if args.output.exists() else {}
offsets = np.array([np.array(p)/np.linalg.norm(p) for p in itertools.product([-1, 0, 1], repeat=3) if any(p)])*.18
neighbors = [np.array(p) for p in itertools.product([-1, 0, 1], repeat=3) if any(p)]


def dense(points, spacing=.08):
    return np.concatenate([a+(b-a)*np.linspace(0, 1, max(2, int(np.linalg.norm(b-a)/spacing)+1))[:, None]
                           for a, b in zip(points, points[1:])])


for key in args.config or frames:
    root = args.touch_breps if key.startswith('touch') else args.base_breps
    solid = cq.Shape.importBrep(str(root/(key+'-Thumb-AP.brep')))
    mesh = render_mesh(solid, .03, .1)
    mesh.ray = trimesh.ray.ray_pyembree.RayMeshIntersector(mesh)
    cylinders = []
    for face in solid.Faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if str(surface.GetType()).endswith('Cylinder'):
            cy = surface.Cylinder()
            cylinders.append(dict(radius=cy.Radius(), center=np.array(face.Center().toTuple()),
                                  axis=np.array(cy.Axis().Direction().Coord()),
                                  location=np.array(cy.Location().Coord()),
                                  v=[surface.FirstVParameter(), surface.LastVParameter()],
                                  angle=surface.LastUParameter()-surface.FirstUParameter(),
                                  inward=int(face.wrapped.Orientation()) == 1))
    pins = [c for c in cylinders if abs(c['radius']-1.1)<.001 and c['angle']>6]
    assert len(pins) == 4, (key, 'pin frame')
    origin = np.mean([c['center'] for c in pins], axis=0)
    pockets = [c for c in cylinders if c['inward'] and abs(c['radius']-1.75)<.001
               and c['angle']>3.1 and abs(np.dot(c['axis'], pins[0]['axis']))>.999]
    assert len(pockets) == 2, (key, 'anchor pockets', len(pockets))
    classifier = BRepClass3d_SolidClassifier(solid.wrapped)
    openings = []
    for pocket in pockets:
        candidates = []
        for sign, v in [(-1, pocket['v'][0]), (1, pocket['v'][1])]:
            clear = True
            for distance in [.5, 2, 4, 8, 12, 20]:
                p = pocket['location']+pocket['axis']*(v+sign*distance)
                classifier.Perform(gp_Pnt(*p), 1e-5)
                clear &= classifier.State() not in [TopAbs_IN, TopAbs_ON]
            if clear:
                candidates.append(pocket['axis']*sign)
        assert len(candidates) == 1, (key, 'ambiguous pocket opening')
        openings.append(candidates[0])
    assert np.dot(*openings)>.999, (key, 'pocket directions differ')
    across = openings[0]
    up = np.array(frames[key]['Thumb']['origin'])-origin
    up -= across*np.dot(up, across)
    up /= np.linalg.norm(up)
    front = np.cross(across, up)
    basis = np.array([front, across, up])
    slots = [c for c in cylinders if abs(c['v'][1]-c['v'][0]-.8)<.01
             and abs(np.dot(c['axis'], across))>.999]
    assert slots, (key, 'side slot')
    slot_y = np.median([(c['location']+c['axis']*np.mean(c['v'])-origin)@across for c in slots])

    def free(points, clearance=.2):
        points = np.asarray(points).reshape(-1, 3)
        ok = np.ones(len(points), dtype=bool)
        for off in [np.zeros(3), *offsets]:
            ids = np.flatnonzero(ok)
            if not len(ids):
                break
            ok[ids] &= ~mesh.contains(points[ids]+off)
        ids = np.flatnonzero(ok)
        if len(ids):
            ok[ids] &= trimesh.proximity.closest_point(mesh, points[ids])[1]>clearance
        return ok

    paths = []
    for pocket in sorted(pockets, key=lambda c: np.dot(c['location']-origin, front)):
        ends = np.array([pocket['location']+pocket['axis']*v for v in pocket['v']])
        local_ends = (ends-origin)@basis.T
        seat = local_ends[np.argmax(local_ends[:, 1])].copy()
        target = seat.copy(); target[1] -= .8
        sign = np.sign(seat[0])
        start = np.array([seat[0]+sign*6, slot_y, seat[2]-4])
        lo = np.minimum(start, target)-[.2, .05, 1]
        hi = np.maximum(start, target)+[.2, .05, 1]
        # Stay below the pocket mouth so a route cannot bypass the side slot in open air.
        step = .18
        shape = np.ceil((hi-lo)/step).astype(int)+1
        grid = ((lo+np.indices(shape).reshape(3, -1).T*step)@basis+origin).reshape(*shape, 3)
        valid = free(grid.reshape(-1, 3), .24).reshape(shape)
        indices, world = np.argwhere(valid), grid[valid]
        a_world, b_world = start@basis+origin, target@basis+origin

        def seed(point):
            for i in np.argsort(np.linalg.norm(world-point, axis=1))[:100]:
                if free(dense([point, world[i]])).all():
                    return tuple(indices[i])
            raise ValueError((key, 'no seed', point))

        a, b = seed(a_world), seed(b_world)
        queue, costs, back = [(0, 0, a)], {a: 0}, {}
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost != costs[node]:
                continue
            if node == b:
                break
            n = np.array(node)
            for off in neighbors:
                nxt = n+off; t = tuple(nxt)
                if np.any(nxt<0) or np.any(nxt>=shape) or not valid[t]:
                    continue
                if any(not valid[tuple(n+np.eye(3, dtype=int)[i]*off[i])] for i in range(3) if off[i]):
                    continue
                ng = cost+np.linalg.norm(off)
                if ng<costs.get(t, float('inf')):
                    costs[t] = ng; back[t] = node
                    heapq.heappush(queue, (ng+np.linalg.norm(nxt-np.array(b)), ng, t))
        assert b in costs, (key, 'no anchor path')
        chain, node = [b], b
        while node != a:
            node = back[node]; chain.append(node)
        mouth = (seat+np.array([0, .5, 0]))@basis+origin
        path = np.array([a_world, *[grid[i] for i in reversed(chain)], b_world, mouth])
        simple, i = [path[0]], 0
        while i<len(path)-1:
            j = min(len(path)-1, i+18)
            while j>i+1 and not free(dense([path[i], path[j]])).all():
                j -= 1
            simple.append(path[j]); i = j
        path = dense(np.array(simple), .12)
        assert free(dense(path, .04)).all(), (key, 'path clearance')
        paths.append(path.round(5).tolist())
        print(key, 'anchor', int(sign), 'samples', len(path), flush=True)
    result[key] = dict(paths=paths, up=across.round(8).tolist(), across=up.round(8).tolist(),
                       front=front.round(8).tolist())
    args.output.write_text(json.dumps(result, separators=(',', ':'))+'\n')

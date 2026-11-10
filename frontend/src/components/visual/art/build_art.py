"""Line drawings of the visual calibration page (one per step) -> *.svg here.

Same hidden-line renderer and geometry as the rig's assembly manual
(orca_files/calibration_rig/manual: hl.py, geometry/*.stl, orca_hand.npz). The
calibration object is not exported yet: it is built from the rig config
(orca_core experiments/visual_calibration rigs/v1/camera-rig/config.yaml:
80 mm tube, 78 mm tiles, rows, lean, face distance, side0_stop) until its STL
lands in geometry/; then load that instead of `calibration_object()`.

The SVGs carry classes, not colours (theme.css `.visual-cal-art`): n = this
step's part, o = parts already in place, i = feature edges, f = tile squares,
a = arrows and dashes, t = labels. Strokes are non-scaling, so widths are px.

  ~/orca_dev/orca_files/.cad-venv/bin/python build_art.py   (about a minute)
"""
import math, os, sys
import numpy as np

MANUAL = os.path.expanduser(os.environ.get('RIG_MANUAL', '~/orca_dev/orca_files/calibration_rig/manual'))
sys.path.insert(0, os.path.join(MANUAL, '../../scripts/manual')); os.environ.setdefault('MANUAL_GEO', f'{MANUAL}/geometry')   # hl.py moved to orca_files scripts/manual/
from hl import View, by_item, mesh, FILES, render, _zbuffer  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
DISPLAY_PX = 560                     # width the page shows a drawing at; sizes labels and arrow heads

def rotz(t, deg, about=(0, 0)):
    r = math.radians(deg)
    R = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return np.asarray(t, float) @ R.T


# ---------------------------------------------------------------- rig, assembly coordinates (camera toward +y)
P = {k: by_item(k) for k in ['rig_base', 'XC-430', 'OH_PCB', 'bearing_holder', 'bearing_6810_2rs_50x65x7',
                             'bearing_clamp_ring', 'rig_plate_v3', 'cam_rail', 'cam_slider', 'cam_column_lower',
                             'cam_mast', 'cam_platform', 'webcam',
                             'franka_connector']}
RODS = [mesh(f['file']) for f in FILES if f['bom_item'] == 'threaded_rod_m5x80']
HAND = np.load(f'{MANUAL}/orca_hand.npz')['tris'].astype(float)   # palm toward -x, thumb -y (CAD mount at plate 0)
BASE = [P[k] for k in ['rig_base', 'XC-430', 'OH_PCB', 'bearing_holder', 'bearing_6810_2rs_50x65x7', 'bearing_clamp_ring']]
MOUNT = [P[k] for k in ['cam_rail', 'cam_slider', 'cam_column_lower', 'cam_mast', 'cam_platform']]
PLATE = P['rig_plate_v3']
MOUNTING = 90.0                      # found mounting: the connector sits 90° from CAD, rods across the camera's view at 180°
CONNECTOR = [rotz(t, MOUNTING) for t in [P['franka_connector'], *RODS]]
CAM = P['webcam']
LENS = np.array([0.0, 224.06, 300.0])       # front of the webcam, roughly the lens centre

# ---------------------------------------------------------------- calibration object (rig config v1)
SIDE0_STOP = 180.0
FACE = 46.0
ROWS = [(150.0, 0.0, (0, 2)), (239.0, 0.0, (0, 1, 2, 3)), (320.0, 25.0, (0, 2))]
TILE, SQ, MARGIN = 78.0, 14.0, 4.0
TUBE, TOP, ROUND_R, ROUND_TOP = 40.0, 360.0, 41.5, 45.0
SEAT = 8.0                            # the object stands on the connector (8 mm)


def quad(a, b, c, d):
    return [[a, b, c], [a, c, d]]


def box(o, ex, ey, ez):
    """Box from corner o along three edge vectors."""
    o, ex, ey, ez = map(np.asarray, (o, ex, ey, ez))
    v = [o + i * ex + j * ey + k * ez for k in (0, 1) for j in (0, 1) for i in (0, 1)]
    f = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    return np.array([t for a, b, c, d in f for t in quad(v[a], v[b], v[c], v[d])])


def ring(z, pts):
    return np.column_stack([pts, np.full(len(pts), z)])


def loft(r0, r1):
    n = len(r0)
    return np.array([t for i in range(n) for t in quad(r0[i], r0[(i + 1) % n], r1[(i + 1) % n], r1[i])])


def tile_frame(row, side):
    h, lean_deg, _ = ROWS[row]
    lean = math.radians(lean_deg)
    phi = math.radians(-SIDE0_STOP + 90 * side)
    z = np.array([0, 0, 1.0])
    n = np.array([math.cos(phi), math.sin(phi), 0])
    right = np.array([-math.sin(phi), math.cos(phi), 0])
    up = math.cos(lean) * z + math.sin(lean) * n
    normal = math.cos(lean) * n - math.sin(lean) * z
    bottom = FACE * n + (h - TILE / 2 * math.cos(lean)) * z
    return bottom + TILE * up - TILE / 2 * right, right, -up, -normal, n, bottom


def calibration_object():
    """(body triangles, tile triangles, checker squares as (centre, 4 corners, outward normal)), plate frame."""
    k = 96
    a = np.linspace(0, 2 * math.pi, k, endpoint=False)
    c, s = np.cos(a), np.sin(a)
    circ = np.column_stack([c, s]) * ROUND_R
    sq = np.column_stack([c, s]) * (TUBE / np.maximum(np.abs(c), np.abs(s)))[:, None]
    # 45° cone from the round base out to the square: the walls end on the curve where it meets them
    rs = np.linalg.norm(sq, axis=1)
    foot = np.column_stack([sq, ROUND_TOP + np.maximum(0, rs - ROUND_R)])
    body = [loft(ring(0, circ), ring(ROUND_TOP, circ)), loft(ring(ROUND_TOP, circ), foot), loft(foot, ring(TOP, sq))]
    corners = np.array([[TUBE, TUBE], [-TUBE, TUBE], [-TUBE, -TUBE], [TUBE, -TUBE]])
    inner = corners * (TUBE - 4) / TUBE
    o1, i1 = ring(TOP, corners), ring(TOP, inner)
    for i in range(4):
        j = (i + 1) % 4
        body.append(np.array(quad(o1[i], o1[j], i1[j], i1[i])))
        body.append(np.array(quad(i1[j], i1[i], i1[i] - (0, 0, 60), i1[j] - (0, 0, 60))))
    tiles, squares = [], []
    for row, (h, lean, sides) in enumerate(ROWS):
        for side in sides:
            tl, x, y, zin, n, bottom = tile_frame(row, side)
            tiles.append(box(tl, x * TILE, y * TILE, zin * 5))
            if lean:
                back_bottom = bottom + zin * 5
                back_top = tl + zin * 5 + x * TILE / 2
                wall_bottom = TUBE * n + bottom[2] * np.array([0, 0, 1])
                wall_top = TUBE * n + back_top[2] * np.array([0, 0, 1])
                sec = [wall_bottom, back_bottom, back_top, wall_top]
                for i in range(4):
                    j = (i + 1) % 4
                    body.append(np.array(quad(sec[i] - x * 39, sec[j] - x * 39, sec[j] + x * 39, sec[i] + x * 39)))
                body.append(np.array([t for t in quad(*[p - x * 39 for p in sec])]))
                body.append(np.array([t for t in quad(*[p + x * 39 for p in sec[::-1]])]))
            for i in range(5):
                for j in range(5):
                    if (i + j) % 2:
                        continue
                    p0 = tl + x * (MARGIN + SQ * i) + y * (MARGIN + SQ * j) - zin * 0.01
                    sqc = [p0, p0 + x * SQ, p0 + x * SQ + y * SQ, p0 + y * SQ]
                    squares.append((p0 + (x + y) * SQ / 2, sqc, -zin))
    return np.concatenate(body), np.concatenate(tiles), squares


def on_rig(t, plate_deg, lift=0.0):
    """Plate frame (x toward the camera at 0°) at a plate angle -> assembly coordinates (camera at +y)."""
    return rotz(t, 90 + plate_deg) + (0, 0, SEAT + lift)


OBJ_BODY, OBJ_TILES, OBJ_SQUARES = calibration_object()


def obj(plate_deg, lift=0.0):
    sq = [(on_rig(c, plate_deg, lift), [on_rig(q, plate_deg, lift) for q in qs], rotz(n, 90 + plate_deg))
          for c, qs, n in OBJ_SQUARES]
    return np.concatenate([on_rig(OBJ_BODY, plate_deg, lift), on_rig(OBJ_TILES, plate_deg, lift)]), sq


# ---------------------------------------------------------------- drawing
class Drawing:
    def __init__(self, view, items, squares=(), ppm=3.0, pad=6):
        self.view, self.ppm = view, ppm
        self.r = render(items, view, ppm, pad=pad)
        self.lo, self.size = self.r['lo'], self.r['size']
        self.k = DISPLAY_PX / self.size[0]          # px per drawing mm
        self.ann = []
        self.fills = self._visible(items, squares)

    def p(self, q):
        return self.view.proj(np.asarray(q, float))[..., :2] - self.lo

    def _visible(self, items, squares):
        """Tile squares that face the viewer and are not hidden by another part."""
        if not squares:
            return []
        T = np.concatenate([t for t, _ in items])
        Pj = self.view.proj(T.reshape(-1, 3)).reshape(-1, 3, 3)
        W, H = (np.ceil(self.size * self.ppm)).astype(int) + 2
        zb = _zbuffer((Pj[..., :2] - self.lo) * self.ppm, Pj[..., 2], W, H)
        out = []
        for c, qs, n in squares:
            if n @ self.view.d <= 0.05:
                continue
            q = self.view.proj(c)
            x, y = ((q[:2] - self.lo) * self.ppm).astype(int)
            if 0 <= x < W and 0 <= y < H and q[2] <= zb[y, x] + 2.0:
                out.append([self.p(v) for v in qs])
        return out

    def arrow(self, pts3d, head=True):
        pts = [self.p(q) for q in pts3d]
        self.ann.append(('arrow', pts, head))

    def dash(self, a, b):
        self.ann.append(('dash', [self.p(a), self.p(b)], False))

    def label(self, q, text, dx=0, dy=0, anchor='middle', leader=None):
        """dx, dy in px at display size."""
        self.ann.append(('label', self.p(q), (text, dx / self.k, dy / self.k, anchor, leader)))

    def parts(self):
        k = self.k
        groups = {}
        for (sid, kind), segs in self.r['segs'].items():
            style = self.r['styles'][sid]
            groups.setdefault((style, kind), []).extend(segs)
        lo, hi = np.zeros(2), self.size.copy()
        for kind, pts, extra in self.ann:
            if kind == 'label':
                text, dx, dy, anchor, _ = extra
                w = len(text) * 0.62 * 14 / k
                x0 = pts[0] + dx - (w if anchor == 'end' else w / 2 if anchor == 'middle' else 0)
                lo = np.minimum(lo, (x0, pts[1] + dy - 14 / k)); hi = np.maximum(hi, (x0 + w, pts[1] + dy + 4 / k))
            else:
                ext = 26 / k if kind == 'lamp' else 6 / k
                for p in (pts if kind != 'lamp' else [pts]):
                    lo = np.minimum(lo, p - ext); hi = np.maximum(hi, p + ext)
        lo, hi = lo - 4 / k, hi + 4 / k
        out = []
        if self.fills:
            d = ''.join('M' + 'L'.join('%.1f %.1f' % tuple(v) for v in qs) + 'Z' for qs in self.fills)
            out.append(f'<path class="f" d="{d}"/>')
        for style in ('o', 'n'):
            for kind in ('in', 'out'):
                segs = groups.get((style, kind))
                if not segs:
                    continue
                d = ''.join('M%.1f %.1fL%.1f %.1f' % (a[0], a[1], b[0], b[1]) for a, b in segs)
                out.append(f'<path class="{style}{" i" if kind == "in" else ""}" d="{d}"/>')
        for kind, pts, extra in self.ann:
            if kind == 'dash':
                (a, b) = pts
                out.append(f'<path class="a d" d="M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}"/>')
            elif kind == 'arrow':
                d = 'M' + 'L'.join('%.1f %.1f' % tuple(p) for p in pts)
                out.append(f'<path class="a" d="{d}"/>')
                B, A = pts[-1], pts[-2]
                u = (B - A) / np.linalg.norm(B - A)
                nrm = np.array([-u[1], u[0]])
                hl, hw = 11 / k, 5 / k
                C = B - u * hl
                tri = [B, C + nrm * hw, C - nrm * hw]
                out.append('<path class="ah" d="M' + 'L'.join('%.1f %.1f' % tuple(p) for p in tri) + 'Z"/>')
            elif kind == 'lamp':
                c, r = pts, 9 / k
                rays = ''.join('M%.1f %.1fL%.1f %.1f' % (c[0] + math.cos(t) * r * 1.6, c[1] + math.sin(t) * r * 1.6,
                                                        c[0] + math.cos(t) * r * 2.4, c[1] + math.sin(t) * r * 2.4)
                               for t in np.radians(np.arange(0, 360, 45)))
                out.append(f'<circle class="a" cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="{r:.1f}"/><path class="a" d="{rays}"/>')
            elif kind == 'label':
                text, dx, dy, anchor, leader = extra
                x, y = pts[0] + dx, pts[1] + dy
                if leader:
                    out.append(f'<path class="a" d="M{pts[0]:.1f} {pts[1]:.1f}L{x:.1f} {y - 4 / k:.1f}"/>')
                out.append(f'<text class="t" x="{x:.1f}" y="{y:.1f}" font-size="{14 / k:.2f}" '
                           f'text-anchor="{anchor}">{text}</text>')
            elif kind == 'cross':
                out.append(f'<path class="a x" d="M{pts[0]:.1f} {pts[1]:.1f}L{extra[0]:.1f} {extra[1]:.1f}'
                           f'M{extra[0]:.1f} {pts[1]:.1f}L{pts[0]:.1f} {extra[1]:.1f}"/>')
        return lo, hi, out

    def cross(self):
        """Big X over the drawing: how not to."""
        W, H = self.size
        self.ann.append(('cross', np.array([W * .1, H * .1]), np.array([W * .9, H * .9])))

    def svg(self, title, inset=None):
        """inset: a second Drawing, smaller, left of this one and bottom-aligned (a wrong way, crossed out)."""
        lo, hi, out = self.parts()
        if inset:
            ilo, ihi, iout = inset.parts()
            s = 0.42 * (hi[1] - lo[1]) / (ihi[1] - ilo[1])
            x, y = lo[0] - (ihi[0] - ilo[0]) * s - 12 / self.k, hi[1] - (ihi[1] - ilo[1]) * s
            out.append(f'<g transform="translate({x - ilo[0] * s:.1f} {y - ilo[1] * s:.1f}) scale({s:.4f})">')
            out += iout + ['</g>']
            lo = np.array([x, lo[1]])
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{lo[0]:.1f} {lo[1]:.1f} {hi[0] - lo[0]:.1f} {hi[1] - lo[1]:.1f}" '
                f'role="img" aria-label="{title}">\n' + '\n'.join(out) + '\n</svg>\n')


def old(*ts):
    return [(t, 'o') for t in ts]


def new(*ts):
    return [(t, 'n') for t in ts]


def arc(r, a0, a1, z=0.0, n=40):
    a = np.radians(np.linspace(a0, a1, n))
    return [np.array([r * math.cos(t), r * math.sin(t), z]) for t in a]


def write(name, drawing, title, inset=None):
    with open(f'{OUT}/{name}.svg', 'w') as fh:
        fh.write(drawing.svg(title, inset))
    print(name, drawing.size.round(), len(drawing.fills), 'squares')


# ---------------------------------------------------------------- the steps
RIG = BASE + MOUNT + [PLATE]
V_FRONT = View(142, 14)              # from the camera's side: object left, mount right


def axis_point(deg, r, z):
    return np.array([r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)), z])


def d_mount():
    lift = 140
    body, sq = obj(SIDE0_STOP, lift)
    d = Drawing(V_FRONT, old(*RIG, CAM) + new(*CONNECTOR, body), sq)
    for r in CONNECTOR[1:]:
        q = r.reshape(-1, 3).mean(0)
        d.dash((q[0], q[1], 80), (q[0], q[1], SEAT + lift))
    a = axis_point(-38, 78, 0)
    d.arrow([a + (0, 0, SEAT + lift + 60), a + (0, 0, SEAT + 60)])
    d.label(on_rig(np.array([-ROUND_R, 0, 20]), SIDE0_STOP, lift), '0 → CAMERA', 80, 30, 'start', leader=True)
    write('mount', d, 'The calibration object goes onto the hand connector, side 0 toward the camera')


def d_camera():
    body, sq = obj(SIDE0_STOP)
    d = Drawing(View(112, 8), old(*RIG, *CONNECTOR, body) + new(CAM), sq)
    lens = CAM.reshape(-1, 3).mean(0)
    ax = np.array([0, 0, 245.8]) - lens
    ax /= np.linalg.norm(ax)
    up = np.cross(ax, np.cross([0, 0, 1.0], ax))
    up /= np.linalg.norm(up)
    for t in (-29, 29):                 # 58° vertical: the 65° diagonal mode, portrait
        r = math.radians(t)
        d.dash(lens, lens + (ax * math.cos(r) + up * math.sin(r)) * 250)
    write('camera', d, 'The BRIO on its side in the mount, looking at the object')


def d_light():
    body, sq = obj(SIDE0_STOP)
    d = Drawing(View(180, 8), old(*BASE, PLATE, *CONNECTOR) + new(body), sq)
    for sgn in (-1, 1):
        c = np.array([sgn * 150, 120, 270])
        d.ann.append(('lamp', d.p(c), None))
        for z in (230, 270, 310):
            d.arrow([c + (-sgn * 26, -10, (z - 270) * 0.35), (sgn * 68, 0, z)])
    write('light', d, 'Even light from both sides, no glare on the tiles')


def hand(wrong=False):
    """The hand at the parked 180°: palm toward the camera, thumb on its right (-x); wrong = turned 180°."""
    return rotz(HAND, MOUNTING + 180 + (180 if wrong else 0))


def d_swap():
    body, sq = obj(SIDE0_STOP)
    off = np.array([190, -150, 110])
    d = Drawing(V_FRONT, old(*RIG, CAM, *CONNECTOR, body + off) + new(hand() + (0, 0, 50)), [])
    d.arrow([(75, -65, 50), (150, -125, 100)])
    d.arrow([(-60, 70, 420), (-60, 70, 340)])
    d.label((0, 45, 270), 'PALM → CAMERA', 70, -60, 'start')
    w = Drawing(V_FRONT, old(PLATE, *CONNECTOR, hand(True)), [], ppm=2.0)
    w.cross()
    write('swap', d, 'Palm toward the camera · thumb on the right', inset=w)


if __name__ == '__main__':
    for f in (d_mount, d_camera, d_light, d_swap):
        f()

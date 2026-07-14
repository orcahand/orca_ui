#!/usr/bin/env python
"""Build the browser-ready 3D hand asset bundle for orca_ui.

This is a manually-run preprocessing CLI (NOT shipped in the wheel). It
converts the v2 ORCA hand description (URDF + MJCF + STL meshes) into a
committed bundle under ``orca_ui/models/hand_v2/``:

    orca_ui/models/hand_v2/
    ├── right/
    │   ├── hand.urdf               # canonical joint/link names, GLB mesh refs
    │   ├── manifest.json
    │   ├── joint_map.yaml          # provenance: machine name -> canonical id
    │   ├── fingertips.yaml         # per finger: fingertip link + tip anchor [m]
    │   └── meshes/*.glb
    └── left/                       # same layout

Run with:

    uv sync --group assets
    uv run --group assets python scripts/build_hand_bundle.py

Design notes
------------

Name mapping. The source URDF/MJCF use machine-generated Fusion export
names ("P-AP_f5e42b61"). Canonical joint ids come from orca_core's
config.yaml. The mapping is derived from the MJCF, whose joint names are
human-readable ("right_m-abd"): for each MJCF body carrying a joint we strip
the side prefix to get the machine link name and find the URDF joint whose
CHILD link matches it exactly. If exact matching fails, we fall back to
matching by joint world position at the zero pose (< 1 mm, with the
second-best candidate > 5 mm away). This is what disambiguates the two
"M-AP" chains (middle vs ring share part geometry and part names; only the
MJCF joint names and the FK cross-check tell them apart).

Frames. GLB root frame = the URDF link's VISUAL frame. Every URDF visual
origin has rpy == 0, and the MJCF body frame coincides with that visual
frame (MJCF geom offsets are numerically ~identity). We KEEP the visual
<origin xyz> in the rewritten URDF and bake into the GLB vertices only:
(a) the mm->m scale (x0.001) and (b) each MJCF geom's pos/quat offset
(snapped to exact identity when below 1e-9). Therefore the rewritten URDF
mesh references carry NO scale attribute.

Axes. MJCF joint axes are expressed in the body frame; URDF axes in the
child link frame. As attached to the physical part these frames coincide
up to a pure translation (URDF visual rpy == 0; verified empirically on
right_wrist first — identical axis components — and enforced for every
joint via the rotational residual below), so axes are compared directly in
that shared local frame.

Rest pose. The two models do NOT share a zero pose on the right side: the
right URDF bakes a -35 deg wrist offset (exactly the wrist ROM bound) into
the wrist joint origin, while the MJCF rest pose holds the palm straight;
the left side agrees everywhere. The URDF wrist limits are the ones that
match orca_core's ROM, so the URDF convention is kept. The FK smoke test
therefore solves, per joint in tree order, the angle about the *known*
joint axis that aligns the URDF chain with the MJCF chain, then requires
(a) the remaining rotational residual to be < 1e-9 and (b) the joint anchor
world positions to agree < 1e-4 m. A swapped middle/ring mapping still
fails loudly (the mount points are ~22 mm apart, which no rotation about
the parent axis can absorb). Non-zero solved offsets are reported and
recorded in the manifest (rest_pose_offsets_deg).

Sub-part meshes. Each link's visual geometry is taken from the MJCF geom
list of the matching body (sub-part STLs + rgba) rather than the URDF's
monolithic assembly STL, which yields the two-tone look. Color LUT:
rgba "0 0 0 1" -> #212529, "1 1 1 1" -> #e8eaed (pure black/white are dead
under PBR lighting).

Dedup. Middle and ring links share identical part meshes; GLBs are deduped
by content hash, so ring_* link visuals reference the middle_* GLB files
(written once per side). Same for any other byte-identical GLB.

Angle convention. orca_core degrees map onto the URDF 1:1 (urdf_rad =
deg2rad(angle_deg)); the ROM report below is the audit trail that would
flag a joint whose URDF limits stop matching orca_core's ROM.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

try:
    import trimesh
    from trimesh.visual.material import PBRMaterial
    import fast_simplification
except ImportError as e:  # pragma: no cover
    sys.exit(
        f"missing asset-pipeline dependency ({e}); install with "
        "`uv sync --group assets` and run via "
        "`uv run --group assets python scripts/build_hand_bundle.py`"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = 1
BUILT_WITH = "build_hand_bundle.py"

# --- canonical naming -------------------------------------------------------

# MJCF clean joint name (side prefix stripped) -> canonical joint id.
CLEAN_JOINT_TO_CANONICAL = {
    "wrist": "wrist",
    "t-cmc": "thumb_cmc",
    "t-abd": "thumb_abd",
    "t-mcp": "thumb_mcp",
    "t-pip": "thumb_dip",  # note: MJCF calls the thumb distal joint "pip"
    "i-abd": "index_abd",
    "i-mcp": "index_mcp",
    "i-pip": "index_pip",
    "m-abd": "middle_abd",
    "m-mcp": "middle_mcp",
    "m-pip": "middle_pip",
    "r-abd": "ring_abd",
    "r-mcp": "ring_mcp",
    "r-pip": "ring_pip",
    "p-abd": "pinky_abd",
    "p-mcp": "pinky_mcp",
    "p-pip": "pinky_pip",
}

# canonical joint id -> canonical name of its CHILD link.
CANONICAL_CHILD_LINK = {
    "wrist": "carpals",
    "thumb_cmc": "thumb_tp",
    "thumb_abd": "thumb_ap",
    "thumb_mcp": "thumb_pp",
    "thumb_dip": "thumb_dp",
}
for _f in ("index", "middle", "ring", "pinky"):
    CANONICAL_CHILD_LINK[f"{_f}_abd"] = f"{_f}_ap"
    CANONICAL_CHILD_LINK[f"{_f}_mcp"] = f"{_f}_pp"
    CANONICAL_CHILD_LINK[f"{_f}_pip"] = f"{_f}_fingertip_assembly"

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# fingertip anchors live on these links (the last mesh-bearing link per finger)
FINGERTIP_PARENT_LINK = {
    "thumb": "thumb_dp",
    "index": "index_fingertip_assembly",
    "middle": "middle_fingertip_assembly",
    "ring": "ring_fingertip_assembly",
    "pinky": "pinky_fingertip_assembly",
}

# Deterministic link order for mesh export, so the GLB content-hash dedupe
# assigns shared middle/ring meshes the middle_* file names.
LINK_EXPORT_ORDER = [
    "forearm", "tower", "carpals",
    "thumb_tp", "thumb_ap", "thumb_pp", "thumb_dp",
    "index_ap", "index_pp", "index_fingertip_assembly",
    "middle_ap", "middle_pp", "middle_fingertip_assembly",
    "ring_ap", "ring_pp", "ring_fingertip_assembly",
    "pinky_ap", "pinky_pp", "pinky_fingertip_assembly",
]

# rgba (as written in the MJCF) -> PBR base color. Pure black/white read
# dead/flat under PBR lighting, hence the tinted substitutes.
COLOR_LUT = {
    (0.0, 0.0, 0.0, 1.0): ("#212529", (0x21 / 255, 0x25 / 255, 0x29 / 255, 1.0)),
    (1.0, 1.0, 1.0, 1.0): ("#e8eaed", (0xE8 / 255, 0xEA / 255, 0xED / 255, 1.0)),
}
METALLIC = 0.1
ROUGHNESS = 0.6

MM_TO_M = 0.001


# --- small math helpers ------------------------------------------------------

def rpy_to_matrix(rpy):
    """URDF fixed-axis rpy -> 3x3 rotation: R = Rz(y) @ Ry(p) @ Rx(r)."""
    r, p, y = rpy
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def quat_to_matrix(q):
    """MuJoCo quaternion (w, x, y, z) -> 3x3 rotation."""
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def make_tf(pos, rot):
    t = np.eye(4)
    t[:3, :3] = rot
    t[:3, 3] = pos
    return t


def floats(s, default=None):
    if s is None:
        return default
    return [float(v) for v in s.split()]


# --- source model parsing ----------------------------------------------------

@dataclass
class UrdfJoint:
    name: str
    type: str
    parent: str
    child: str
    origin_xyz: list
    origin_rpy: list
    axis: list | None
    lower: float | None
    upper: float | None
    element: object


@dataclass
class UrdfLink:
    name: str
    visual_origin_xyz: list
    element: object


@dataclass
class UrdfModel:
    robot_name: str
    links: dict            # name -> UrdfLink
    joints: list           # [UrdfJoint] in document order
    root: str

    def joint_by_child(self):
        return {j.child: j for j in self.joints}

    def world_tf(self):
        """link name -> 4x4 world transform at zero pose."""
        tf = {self.root: np.eye(4)}
        pending = list(self.joints)
        while pending:
            progressed = False
            rest = []
            for j in pending:
                if j.parent in tf:
                    local = make_tf(j.origin_xyz, rpy_to_matrix(j.origin_rpy))
                    tf[j.child] = tf[j.parent] @ local
                    progressed = True
                else:
                    rest.append(j)
            pending = rest
            if not progressed and pending:
                raise SystemExit(
                    f"URDF kinematic tree is disconnected at joints: "
                    f"{[j.name for j in pending]}"
                )
        return tf


def parse_urdf(path: Path) -> UrdfModel:
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    links, joints = {}, []
    for le in root.findall("link"):
        vis = le.find("visual")
        origin = [0.0, 0.0, 0.0]
        if vis is not None:
            oe = vis.find("origin")
            if oe is not None:
                origin = floats(oe.get("xyz"), [0.0, 0.0, 0.0])
                rpy = floats(oe.get("rpy"), [0.0, 0.0, 0.0])
                if any(abs(v) > 1e-9 for v in rpy):
                    raise SystemExit(
                        f"{path.name}: link {le.get('name')} visual origin has "
                        f"non-zero rpy {rpy}; the visual-frame convention of this "
                        "script assumes rpy == 0 (see module docstring)"
                    )
        links[le.get("name")] = UrdfLink(le.get("name"), origin, le)
    for je in root.findall("joint"):
        oe, ae, lim = je.find("origin"), je.find("axis"), je.find("limit")
        joints.append(UrdfJoint(
            name=je.get("name"),
            type=je.get("type"),
            parent=je.find("parent").get("link"),
            child=je.find("child").get("link"),
            origin_xyz=floats(oe.get("xyz"), [0, 0, 0]) if oe is not None else [0, 0, 0],
            origin_rpy=floats(oe.get("rpy"), [0, 0, 0]) if oe is not None else [0, 0, 0],
            axis=floats(ae.get("xyz")) if ae is not None else None,
            lower=float(lim.get("lower")) if lim is not None else None,
            upper=float(lim.get("upper")) if lim is not None else None,
            element=je,
        ))
    children = {j.child for j in joints}
    roots = [n for n in links if n not in children]
    if len(roots) != 1:
        raise SystemExit(f"{path.name}: expected 1 root link, found {roots}")
    return UrdfModel(root.get("name"), links, joints, roots[0])


@dataclass
class MjcfGeom:
    mesh: str          # asset name (with side prefix)
    rgba: tuple
    pos: list
    quat: list
    visual_only: bool  # contype == 0


@dataclass
class MjcfBody:
    name: str
    parent: str | None
    pos: list
    quat: list
    joints: list = field(default_factory=list)  # [(name, pos, axis, range)]
    geoms: list = field(default_factory=list)


def parse_mjcf(body_xml: Path, asset_mjcf: Path, description: Path):
    """Returns (bodies: dict name->MjcfBody in tree order, mesh_files: dict
    asset name -> resolved STL Path)."""
    import xml.etree.ElementTree as ET

    bodies: dict[str, MjcfBody] = {}

    def walk(el, parent_name):
        b = MjcfBody(
            name=el.get("name"),
            parent=parent_name,
            pos=floats(el.get("pos"), [0.0, 0.0, 0.0]),
            quat=floats(el.get("quat"), [1.0, 0.0, 0.0, 0.0]),
        )
        for je in el.findall("joint"):
            b.joints.append((
                je.get("name"),
                floats(je.get("pos"), [0.0, 0.0, 0.0]),
                floats(je.get("axis"), [0.0, 0.0, 1.0]),
                floats(je.get("range")),
            ))
        for ge in el.findall("geom"):
            rgba = tuple(floats(ge.get("rgba"), [1.0, 1.0, 1.0, 1.0]))
            b.geoms.append(MjcfGeom(
                mesh=ge.get("mesh"),
                rgba=rgba,
                pos=floats(ge.get("pos"), [0.0, 0.0, 0.0]),
                quat=floats(ge.get("quat"), [1.0, 0.0, 0.0, 0.0]),
                visual_only=ge.get("contype") == "0",
            ))
        bodies[b.name] = b
        for child in el.findall("body"):
            walk(child, b.name)

    root = ET.parse(body_xml).getroot()
    for el in root.findall("body"):
        walk(el, None)

    # Mesh asset declarations live in the sibling .mjcf file. Its file paths
    # (e.g. "models/assets/right/X.stl") are resolved by MuJoCo relative to
    # the *including* scene file at v2/, so try a few sensible bases.
    mesh_files = {}
    aroot = ET.parse(asset_mjcf).getroot()
    v2_dir = asset_mjcf.parent.parent.parent  # .../v2
    scale_warn = []
    default_mesh = aroot.find("./default/mesh")
    if default_mesh is not None:
        sc = floats(default_mesh.get("scale"), [1, 1, 1])
        if not all(abs(v - MM_TO_M) < 1e-12 for v in sc):
            scale_warn.append(sc)
    for me in aroot.iter("mesh"):
        name, file = me.get("name"), me.get("file")
        if name is None or file is None:
            continue
        for base in (asset_mjcf.parent, v2_dir, description):
            cand = base / file
            if cand.is_file():
                mesh_files[name] = cand
                break
        else:
            raise SystemExit(f"cannot resolve MJCF mesh file {file!r}")
        if me.get("scale") is not None:
            sc = floats(me.get("scale"))
            if not all(abs(v - MM_TO_M) < 1e-12 for v in sc):
                scale_warn.append(sc)
    if scale_warn:
        raise SystemExit(f"unexpected MJCF mesh scale(s) {scale_warn}; expected 0.001")
    return bodies, mesh_files


def mjcf_world_tf(bodies):
    tf = {}
    for b in bodies.values():  # dict preserves tree (pre-order) insertion
        local = make_tf(b.pos, quat_to_matrix(b.quat))
        tf[b.name] = local if b.parent is None else tf[b.parent] @ local
    return tf


# --- mapping derivation ------------------------------------------------------

def derive_mapping(side, urdf: UrdfModel, bodies, log):
    """Returns (joint_map: machine joint name -> canonical id,
                link_map: machine link name -> canonical link name,
                mjcf_joint_of: canonical id -> (body name, joint tuple))."""
    prefix = side + "_"
    by_child = urdf.joint_by_child()
    urdf_tf = urdf.world_tf()
    m_tf = mjcf_world_tf(bodies)

    joint_map, mjcf_joint_of = {}, {}
    for b in bodies.values():
        for (jname, jpos, jaxis, jrange) in b.joints:
            clean = jname[len(prefix):] if jname.startswith(prefix) else jname
            canonical = CLEAN_JOINT_TO_CANONICAL.get(clean)
            if canonical is None:
                raise SystemExit(f"[{side}] unknown MJCF joint name {jname!r}")
            machine_link = b.name[len(prefix):] if b.name.startswith(prefix) else b.name
            uj = by_child.get(machine_link)
            if uj is None:
                # Fallback: match by joint world position at zero pose.
                target = m_tf[b.name] @ np.array([*jpos, 1.0])
                dists = sorted(
                    (float(np.linalg.norm(urdf_tf[j.child][:3, 3] - target[:3])), j)
                    for j in urdf.joints if j.type == "revolute"
                )
                best_d, best_j = dists[0]
                second_d = dists[1][0] if len(dists) > 1 else float("inf")
                if best_d < 1e-3 and second_d > 5e-3:
                    log(f"[{side}] {jname}: no exact child-link match for "
                        f"{machine_link!r}; matched {best_j.name!r} by position "
                        f"({best_d * 1e3:.3f} mm, runner-up {second_d * 1e3:.1f} mm)")
                    uj = best_j
                else:
                    raise SystemExit(
                        f"[{side}] cannot map MJCF joint {jname!r}: no URDF child "
                        f"link {machine_link!r} and position fallback ambiguous "
                        f"(best {best_d * 1e3:.2f} mm, second {second_d * 1e3:.2f} mm)")
            if uj.type != "revolute":
                raise SystemExit(f"[{side}] {jname} mapped to non-revolute URDF "
                                 f"joint {uj.name}")
            joint_map[uj.name] = canonical
            mjcf_joint_of[canonical] = (b.name, (jname, jpos, jaxis, jrange))

    # Bijection onto the 17 canonical ids.
    canon = sorted(CLEAN_JOINT_TO_CANONICAL.values())
    got = sorted(joint_map.values())
    if got != canon:
        raise SystemExit(f"[{side}] mapping is not a bijection onto the 17 "
                         f"canonical ids: got {got}")
    if len(joint_map) != 17:
        raise SystemExit(f"[{side}] expected 17 mapped joints, got {len(joint_map)}")

    # Canonical link names.
    link_map = {}
    for uj in urdf.joints:
        if uj.name in joint_map:
            link_map[uj.child] = CANONICAL_CHILD_LINK[joint_map[uj.name]]
        elif uj.type == "fixed":
            link_map[uj.child] = "tower"
        else:
            raise SystemExit(f"[{side}] unexpected joint {uj.name!r} of type "
                             f"{uj.type!r}")
    link_map[urdf.root] = "forearm"
    if len(link_map) != len(urdf.links):
        missing = set(urdf.links) - set(link_map)
        raise SystemExit(f"[{side}] links without canonical names: {missing}")
    return joint_map, link_map, mjcf_joint_of


# --- validations -------------------------------------------------------------

def rotation_about_axis(axis, angle):
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def validate_kinematics(side, urdf, bodies, joint_map, mjcf_joint_of, log):
    """FK smoke test + axis check (see module docstring, "Rest pose").
    Returns {canonical id: solved rest-pose offset in degrees} for the
    joints whose URDF and MJCF zero poses disagree (right wrist: -35 deg)."""
    revolute = [j for j in urdf.joints if j.type == "revolute"]
    if len(revolute) != 17:
        raise SystemExit(f"[{side}] expected exactly 17 revolute URDF joints, "
                         f"found {len(revolute)}")

    m_tf = mjcf_world_tf(bodies)
    max_pos_err, min_axis_dot = 0.0, 1.0
    rest_offsets = {}
    # URDF FK re-solved in tree order, absorbing per-joint rest offsets.
    tf = {urdf.root: np.eye(4)}
    for uj in urdf.joints:
        t0 = tf[uj.parent] @ make_tf(uj.origin_xyz, rpy_to_matrix(uj.origin_rpy))
        if uj.type != "revolute":
            tf[uj.child] = t0
            continue
        canonical = joint_map[uj.name]
        body_name, (jname, jpos, jaxis, jrange) = mjcf_joint_of[canonical]

        # Axis alignment in the shared local frame (child link vs body frame,
        # identical orientation as attached to the part; see docstring).
        a_u = np.array(uj.axis) / np.linalg.norm(uj.axis)
        a_m = np.array(jaxis) / np.linalg.norm(jaxis)
        dot = float(np.dot(a_u, a_m))
        min_axis_dot = min(min_axis_dot, dot)
        if dot <= 0.999999:
            raise SystemExit(f"[{side}] axis disagreement at {canonical}: "
                             f"URDF·MJCF = {dot:.9f}")

        # Solve the rest-pose offset about the joint axis that aligns the
        # URDF child frame with the MJCF body frame...
        d = t0[:3, :3].T @ m_tf[body_name][:3, :3]
        angle = math.atan2(
            float(np.array([d[2, 1] - d[1, 2], d[0, 2] - d[2, 0],
                            d[1, 0] - d[0, 1]]) @ a_u) / 2.0,
            (float(np.trace(d)) - 1.0) / 2.0)
        rq = rotation_about_axis(a_u, angle)
        resid = float(np.linalg.norm(rq.T @ d - np.eye(3)))
        if resid >= 1e-9:
            raise SystemExit(f"[{side}] frame disagreement at {canonical}: "
                             f"residual {resid:.2e} after removing a rotation "
                             f"of {math.degrees(angle):.3f} deg about the axis")
        if abs(math.degrees(angle)) > 0.01:
            rest_offsets[canonical] = round(math.degrees(angle), 4)
        tf[uj.child] = t0 @ make_tf([0, 0, 0], rq)

        # ...and require the joint anchor world positions to coincide.
        p_urdf = tf[uj.child][:3, 3]
        p_mjcf = (m_tf[body_name] @ np.array([*jpos, 1.0]))[:3]
        err = float(np.linalg.norm(p_urdf - p_mjcf))
        max_pos_err = max(max_pos_err, err)
        if err >= 1e-4:
            raise SystemExit(f"[{side}] FK mismatch at {canonical} "
                             f"({uj.name} vs {jname}): {err * 1e3:.3f} mm")
    log(f"[{side}] FK smoke test OK (max joint anchor error "
        f"{max_pos_err * 1e3:.4f} mm); axes aligned (min dot {min_axis_dot:.9f})")
    if rest_offsets:
        log(f"[{side}] URDF-vs-MJCF rest-pose offsets (URDF convention kept, "
            f"its limits match orca_core ROMs): {rest_offsets}")
    return rest_offsets


def rom_report(side, urdf, joint_map, core_roms, log):
    """Prints the informational ROM table; returns
    {canonical: (classification, sign)} with classification in
    rom_match | rom_mirrored | ambiguous | rom_mismatch."""
    TOL = 2.0  # degrees
    rows, result = [], {}
    by_name = {j.name: j for j in urdf.joints}
    ordered = [j for j in urdf.joints if j.name in joint_map]  # tree order
    for uj in ordered:
        canonical = joint_map[uj.name]
        lo_u, hi_u = math.degrees(uj.lower), math.degrees(uj.upper)
        lo_c, hi_c = core_roms[canonical]
        direct = abs(lo_u - lo_c) <= TOL and abs(hi_u - hi_c) <= TOL
        mirror = abs(lo_u + hi_c) <= TOL and abs(hi_u + lo_c) <= TOL
        if direct and mirror:
            cls, sign = "ambiguous", 1
        elif direct:
            cls, sign = "rom_match", 1
        elif mirror:
            cls, sign = "rom_mirrored", -1
        else:
            cls, sign = "rom_mismatch", 1
        result[canonical] = (cls, sign)
        rows.append((canonical, lo_u, hi_u, lo_c, hi_c, cls))

    log(f"\n[{side}] ROM report (URDF limits vs orca_core joint_roms, deg):")
    log(f"  {'joint':<12} {'urdf_lo':>8} {'urdf_hi':>8} {'core_lo':>8} "
        f"{'core_hi':>8}  classification")
    for name, lo_u, hi_u, lo_c, hi_c, cls in rows:
        log(f"  {name:<12} {lo_u:>8.1f} {hi_u:>8.1f} {lo_c:>8.1f} "
            f"{hi_c:>8.1f}  {cls}")
    log("")
    return result


# --- mesh pipeline -----------------------------------------------------------

def snap_transform(pos, quat, atol=1e-9):
    t = make_tf(pos, quat_to_matrix(quat))
    return np.eye(4) if np.allclose(t, np.eye(4), atol=atol) else t


class MeshCache:
    """Loads, scales (mm->m), transforms, welds and decimates sub-part STLs.
    Keyed by (file, transform) so shared parts are processed once per side."""

    def __init__(self, divisor, tri_floor, tri_cap, log):
        self.divisor, self.floor, self.cap = divisor, tri_floor, tri_cap
        self.log = log
        self._cache = {}
        self.stats = {}  # key -> (orig_tris, final_tris)

    def get(self, stl_path: Path, transform: np.ndarray):
        key = (str(stl_path), transform.round(12).tobytes())
        if key in self._cache:
            return self._cache[key]
        mesh = trimesh.load(stl_path, force="mesh", process=True)  # welds verts
        mesh.apply_scale(MM_TO_M)
        if not np.allclose(transform, np.eye(4)):
            mesh.apply_transform(transform)
        orig = len(mesh.faces)
        target = max(self.floor, min(self.cap, orig // self.divisor))
        if orig > target:
            v, f = fast_simplification.simplify(
                np.asarray(mesh.vertices, dtype=np.float64),
                np.asarray(mesh.faces, dtype=np.int64),
                target_count=target,
            )
            mesh = trimesh.Trimesh(vertices=v, faces=f, process=True)
        # sanity: decimation must not produce a degenerate mesh
        if len(mesh.faces) == 0 or mesh.area <= 0 or np.isnan(mesh.vertices).any():
            raise SystemExit(f"mesh sanity check failed for {stl_path.name}: "
                             f"{len(mesh.faces)} faces, area {mesh.area}")
        self._cache[key] = mesh
        self.stats[key] = (orig, len(mesh.faces))
        return mesh


def colored_copy(mesh, rgba, mat_cache):
    key = rgba
    if key not in mat_cache:
        lut = COLOR_LUT.get(rgba)
        if lut is None:
            print(f"  warning: rgba {rgba} not in color LUT; using it verbatim")
            name, color = "custom", rgba
        else:
            name, color = lut
        mat_cache[key] = PBRMaterial(
            baseColorFactor=list(color), metallicFactor=METALLIC,
            roughnessFactor=ROUGHNESS, name=name)
    out = mesh.copy()
    out.visual = trimesh.visual.TextureVisuals(material=mat_cache[key])
    return out


def build_link_glbs(side, urdf, bodies, link_map, mesh_files, mesh_cache,
                    out_meshes: Path, log):
    """Exports one GLB per link (content-hash deduped). Returns
    (link_glb: canonical link -> relative mesh path,
     glb_info: filename -> {tris, bytes},
     skin_bounds: canonical link -> (min, max) of its skin sub-meshes,
     pre-decimation, in the link's VISUAL frame)."""
    prefix = side + "_"
    body_of_machine = {name[len(prefix):]: b for name, b in bodies.items()
                       if name.startswith(prefix)}
    mat_cache, hash_to_file = {}, {}
    link_glb, glb_info, skin_bounds = {}, {}, {}

    inv_link_map = {v: k for k, v in link_map.items()}
    order = [l for l in LINK_EXPORT_ORDER if l in inv_link_map]
    order += [l for l in link_map.values() if l not in order]  # safety net

    for canonical_link in order:
        machine = inv_link_map[canonical_link]
        body = body_of_machine.get(machine)
        if body is None or not body.geoms:
            raise SystemExit(f"[{side}] no MJCF geoms found for link "
                             f"{canonical_link} ({machine})")
        scene = trimesh.Scene()
        bounds_min, bounds_max = None, None
        for geom in body.geoms:
            stl = mesh_files.get(geom.mesh)
            if stl is None:
                raise SystemExit(f"[{side}] MJCF geom mesh {geom.mesh!r} has no "
                                 f"asset declaration")
            tf = snap_transform(geom.pos, geom.quat)
            part = mesh_cache.get(stl, tf)
            if geom.rgba == (1.0, 1.0, 1.0, 1.0):  # skin / white sub-meshes
                raw = trimesh.load(stl, force="mesh", process=False)
                raw.apply_scale(MM_TO_M)
                if not np.allclose(tf, np.eye(4)):
                    raw.apply_transform(tf)
                lo, hi = raw.bounds
                bounds_min = lo if bounds_min is None else np.minimum(bounds_min, lo)
                bounds_max = hi if bounds_max is None else np.maximum(bounds_max, hi)
            name = geom.mesh[len(prefix):] if geom.mesh.startswith(prefix) else geom.mesh
            scene.add_geometry(colored_copy(part, geom.rgba, mat_cache),
                               geom_name=name)
        blob = scene.export(file_type="glb")
        digest = hashlib.sha256(blob).hexdigest()
        if digest in hash_to_file:
            fname = hash_to_file[digest]
            log(f"[{side}] link {canonical_link}: reusing {fname} "
                f"(identical content)")
        else:
            fname = f"link_{canonical_link}.glb"
            (out_meshes / fname).write_bytes(blob)
            hash_to_file[digest] = fname
            tris = sum(len(g.faces) for g in scene.geometry.values())
            glb_info[fname] = {"tris": int(tris), "bytes": len(blob)}
        link_glb[canonical_link] = f"meshes/{fname}"
        if bounds_min is not None:
            skin_bounds[canonical_link] = (bounds_min, bounds_max)
    return link_glb, glb_info, skin_bounds


# --- fingertip anchors -------------------------------------------------------

def derive_fingertip_anchors(side, urdf, link_map, skin_bounds, log):
    """Anchor per finger, in the fingertip LINK frame: bbox center on the two
    transverse axes, bbox max along the distal axis. The distal axis is
    verified from the fingertip joint's offset in its parent (PP/thumb-PP)
    frame, rotated into the child frame."""
    inv = {v: k for k, v in link_map.items()}
    by_child = urdf.joint_by_child()
    anchors = {}
    for finger in FINGERS:
        tip_link = FINGERTIP_PARENT_LINK[finger]
        machine = inv[tip_link]
        uj = by_child[machine]
        d_parent = np.array(uj.origin_xyz)
        d_parent /= np.linalg.norm(d_parent)
        # v_parent = R @ v_child  =>  d_child = R.T @ d_parent
        d_child = rpy_to_matrix(uj.origin_rpy).T @ d_parent
        axis = int(np.argmax(np.abs(d_child)))
        sign = 1.0 if d_child[axis] >= 0 else -1.0
        axis_name = "xyz"[axis] if sign > 0 else "-" + "xyz"[axis]
        if not (axis == 2 and sign > 0):
            log(f"[{side}] note: {finger} distal axis is {axis_name}, not +z; "
                f"anchor adjusted accordingly")
        if tip_link not in skin_bounds:
            raise SystemExit(f"[{side}] no skin sub-mesh found on {tip_link}; "
                             f"cannot derive {finger} fingertip anchor")
        lo, hi = skin_bounds[tip_link]  # in the link's visual frame
        anchor_vis = (lo + hi) / 2.0
        anchor_vis[axis] = hi[axis] if sign > 0 else lo[axis]
        # visual frame -> link frame (visual origin is a pure translation)
        vis_origin = np.array(urdf.links[machine].visual_origin_xyz)
        anchor = anchor_vis + vis_origin
        anchors[finger] = {
            "link": f"{finger}_fingertip",
            "parent_link": tip_link,
            "anchor": [round(float(v), 6) for v in anchor],
            "distal_axis": axis_name,
        }
        log(f"[{side}] {finger} fingertip anchor on {tip_link}: "
            f"{anchors[finger]['anchor']} (distal axis {axis_name})")
    return anchors


# --- URDF rewrite -------------------------------------------------------------

def write_urdf(side, urdf, joint_map, link_map, link_glb, anchors, out: Path):
    import xml.etree.ElementTree as ET
    robot = ET.Element("robot", {"name": f"orcahand_{side}"})
    for ul in [urdf.links[n] for n in urdf.links]:
        canonical = link_map[ul.name]
        le = ET.SubElement(robot, "link", {"name": canonical})
        src_inertial = ul.element.find("inertial")
        if src_inertial is not None:
            le.append(src_inertial)
        vis = ET.SubElement(le, "visual")
        ET.SubElement(vis, "origin", {
            "xyz": " ".join(repr(v) for v in ul.visual_origin_xyz),
            "rpy": "0 0 0",
        })
        geo = ET.SubElement(vis, "geometry")
        # scale already baked into the GLB vertices -> no scale attribute
        ET.SubElement(geo, "mesh", {"filename": link_glb[canonical]})
        # (source has no collision elements; none are emitted: viz-only URDF)
    for uj in urdf.joints:
        name = joint_map.get(uj.name, "tower_fixed" if uj.type == "fixed" else None)
        if name is None:
            raise SystemExit(f"[{side}] joint {uj.name} has no canonical name")
        je = ET.SubElement(robot, "joint", {"type": uj.type, "name": name})
        ET.SubElement(je, "parent", {"link": link_map[uj.parent]})
        ET.SubElement(je, "child", {"link": link_map[uj.child]})
        src = uj.element
        for tag in ("origin", "axis", "limit"):
            e = src.find(tag)
            if e is not None:
                je.append(e)
    # fingertip anchor links (massless, no visual)
    for finger in FINGERS:
        a = anchors[finger]
        ET.SubElement(robot, "link", {"name": a["link"]})
        je = ET.SubElement(robot, "joint",
                           {"type": "fixed", "name": f"{finger}_fingertip_fixed"})
        ET.SubElement(je, "parent", {"link": a["parent_link"]})
        ET.SubElement(je, "child", {"link": a["link"]})
        ET.SubElement(je, "origin", {
            "xyz": " ".join(repr(float(v)) for v in a["anchor"]),
            "rpy": "0 0 0",
        })
    tree = ET.ElementTree(robot)
    ET.indent(tree, space="  ")
    tree.write(out, encoding="unicode", xml_declaration=True)
    out.write_text(out.read_text() + "\n")


# --- per-side build -----------------------------------------------------------

def git_source_info(description: Path):
    sha, dirty = None, None
    try:
        sha = subprocess.run(
            ["git", "-C", str(description), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(description), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        dirty = bool(status.strip())
    except Exception:
        pass
    return {"description_path": str(description), "git_sha": sha, "dirty": dirty}


def build_side(side, args, core_roms, source_info, log):
    description = args.description
    urdf_path = description / "v2" / "models" / "urdf" / f"orcahand_{side}.urdf"
    body_xml = description / "v2" / "models" / "mjcf" / f"orcahand_{side}_body.xml"
    asset_mjcf = description / "v2" / "models" / "mjcf" / f"orcahand_{side}.mjcf"
    for p in (urdf_path, body_xml, asset_mjcf):
        if not p.is_file():
            raise SystemExit(f"missing source file: {p}")

    urdf = parse_urdf(urdf_path)
    bodies, mesh_files = parse_mjcf(body_xml, asset_mjcf, description)

    joint_map, link_map, mjcf_joint_of = derive_mapping(side, urdf, bodies, log)
    rest_offsets = validate_kinematics(side, urdf, bodies, joint_map,
                                       mjcf_joint_of, log)
    rom_result = rom_report(side, urdf, joint_map, core_roms, log)

    side_dir = args.out / side
    meshes_dir = side_dir / "meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)
    for stale in meshes_dir.glob("*.glb"):
        stale.unlink()

    mesh_cache = MeshCache(args.target_tris_divisor, args.tri_floor,
                           args.tri_cap, log)
    link_glb, glb_info, skin_bounds = build_link_glbs(
        side, urdf, bodies, link_map, mesh_files, mesh_cache, meshes_dir, log)

    anchors = derive_fingertip_anchors(side, urdf, link_map, skin_bounds, log)
    write_urdf(side, urdf, joint_map, link_map, link_glb, anchors,
               side_dir / "hand.urdf")

    (side_dir / "joint_map.yaml").write_text(
        "# Provenance: original machine-generated names -> canonical ids.\n"
        "# Generated by scripts/build_hand_bundle.py — do not edit.\n"
        + yaml.safe_dump({
            "joints": joint_map,
            "links": {k: v for k, v in link_map.items()},
        }, sort_keys=True))

    (side_dir / "fingertips.yaml").write_text(
        "# Fingertip anchor links and tip anchors (meters, in the parent\n"
        "# fingertip link frame). Generated by scripts/build_hand_bundle.py.\n"
        + yaml.safe_dump(anchors, sort_keys=False))

    total_tris = sum(v["tris"] for v in glb_info.values())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": source_info,
        "side": side,
        "joints": [joint_map[j.name] for j in urdf.joints if j.name in joint_map],
        "links": [link_map[n] for n in urdf.links]
                 + [a["link"] for a in anchors.values()],
        "meshes": glb_info,
        "total_tris": total_tris,
        # URDF-vs-MJCF rest-pose disagreements absorbed by the FK validation
        # (informational; the shipped URDF keeps the URDF convention).
        "rest_pose_offsets_deg": rest_offsets,
        "built_with": BUILT_WITH,
    }
    (side_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    glb_bytes = sum(v["bytes"] for v in glb_info.values())
    log(f"[{side}] bundle written to {side_dir}: {len(glb_info)} GLB files, "
        f"{total_tris} tris, {glb_bytes / 1e6:.2f} MB raw GLB")
    if glb_bytes > 4_000_000:
        raise SystemExit(f"[{side}] GLB budget exceeded: {glb_bytes} bytes > 4 MB")
    return rom_result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--description", type=Path,
                    default=REPO_ROOT.parent / "orcahand_description",
                    help="path to the orcahand_description checkout")
    ap.add_argument("--core-config", type=Path,
                    default=REPO_ROOT.parent / "orca_core" / "orca_core" /
                    "models" / "v2" / "orcahand-right" / "config.yaml",
                    help="orca_core hand config providing joint_ids/joint_roms")
    ap.add_argument("--sides", nargs="+", default=["right", "left"],
                    choices=["right", "left"])
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "orca_ui" / "models" / "hand_v2")
    ap.add_argument("--target-tris-divisor", type=int, default=8)
    ap.add_argument("--tri-floor", type=int, default=1500,
                    help="per-sub-mesh decimation floor (faces)")
    ap.add_argument("--tri-cap", type=int, default=8000,
                    help="per-sub-mesh decimation cap (faces)")
    args = ap.parse_args(argv)
    args.description = args.description.resolve()
    args.out = args.out.resolve()

    log = print
    core_cfg = yaml.safe_load(args.core_config.read_text())
    core_ids = list(core_cfg["joint_ids"])
    if sorted(core_ids) != sorted(CLEAN_JOINT_TO_CANONICAL.values()):
        raise SystemExit("orca_core joint_ids do not match the canonical ids "
                         "known to this script")
    core_roms = {k: [float(v[0]), float(v[1])]
                 for k, v in core_cfg["joint_roms"].items()}

    source_info = git_source_info(args.description)
    log(f"source: {source_info}")

    args.out.mkdir(parents=True, exist_ok=True)
    for side in args.sides:
        build_side(side, args, core_roms, source_info, log)
    log("done")


if __name__ == "__main__":
    main()

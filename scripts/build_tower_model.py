#!/usr/bin/env python
"""Build the hull-less tower model guided tensioning shows the spools on.

A manually-run preprocessing CLI (NOT shipped in the wheel). Reads a v2 base
assembly STEP (``orca_files/orca_v2/base/Orcahand_BaseV2_*.zip``), drops the
two hulls, fasteners and the duplicate motor bodies the CAD export carries,
and writes ``orca_ui/models/hand_v2/<side>/tower_spools.glb`` with named nodes:

    structure        tower frame and spool holders
    hand             wrist, top tower and fingers, so the faces read as palm/back
    motor_<pos>      one per finger motor
    spool_<pos>      its spool, cover and ratchet

``<pos>`` is ``<face><col><row>``: face ``F`` (HullFront side, -z) or ``B``
(HullBack side, +z); col ``1``/``2`` by x; row ``1``-``4`` from the wrist end.
The tower and its spool positions are the same on both sides; only the hand
on top mirrors. Which joint each position drives lives in the frontend
(``towerLayout.ts``).

Run with:

    uv run --group assets --with cadquery-ocp --with scipy \\
        python scripts/build_tower_model.py right path/to/Base_Right.step
"""

from __future__ import annotations

import argparse
import os
import re

import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.OCP.collections import Sequence_TDF_Label
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import XCAFDoc_DocumentTool

MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "orca_ui", "models", "hand_v2")
SPOOL = re.compile(r"BaseSpool|SpoolCover|Ratchet|SpoolTensioner", re.I)
FASTENER = re.compile(r"screw|nut\b|nut |washer|bearing|pin-|magnet|PHS_|BTS|FHS|B3B|insert|EHR|JST|_0805|TQFP|TSOT", re.I)
LINEAR_DEFLECTION_MM = 0.5
TARGET_REDUCTION = {"structure": 0.7, "hand": 0.85, "motor": 0.85, "spool": 0.6}


class Assembly:
    def __init__(self, path: str):
        self.doc = TDocStd_Document(TCollection_ExtendedString("doc"))
        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        reader.ReadFile(path)
        reader.Transfer(self.doc)
        self.st = XCAFDoc_DocumentTool.ShapeTool_s(self.doc.Main())

    def name(self, label) -> str:
        attr = TDataStd_Name()
        return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""

    def resolve(self, label):
        if self.st.IsReference_s(label):
            ref = TDF_Label()
            self.st.GetReferredShape_s(label, ref)
            return ref
        return label

    def place(self, label, loc):
        return loc.Multiplied(self.st.GetLocation_s(label)) if self.st.IsReference_s(label) else loc

    def children(self, label):
        seq = Sequence_TDF_Label()
        self.st.GetComponents_s(label, seq, False)
        return [seq.Value(i) for i in range(1, seq.Length() + 1)]

    def roots(self):
        seq = Sequence_TDF_Label()
        self.st.GetFreeShapes(seq)
        return [seq.Value(i) for i in range(1, seq.Length() + 1)]


def tessellate(shape) -> trimesh.Trimesh | None:
    BRepMesh_IncrementalMesh(shape, LINEAR_DEFLECTION_MM, False, 0.6, True)
    verts, faces, offset = [], [], 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            flip = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = (offset + v - 1 for v in tri.Triangle(i).Get())
                faces.append((a, c, b) if flip else (a, b, c))
            offset += tri.NbNodes()
        explorer.Next()
    if not faces:
        return None
    return trimesh.Trimesh(np.array(verts), np.array(faces), process=False)


def centre(shape) -> tuple:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    a, b = box.CornerMin(), box.CornerMax()
    return tuple(round(v, 1) for v in ((a.X() + b.X()) / 2, (a.Y() + b.Y()) / 2, (a.Z() + b.Z()) / 2))


def collect(asm: Assembly):
    structure, hand, motors = [], [], {}

    def leaves(label, loc, spools, bodies, in_spool=False):
        ref = asm.resolve(label)
        here = asm.place(label, loc)
        n = f"{asm.name(label)} {asm.name(ref)}"
        if FASTENER.search(n):
            return
        spoolish = in_spool or bool(SPOOL.search(n))
        if asm.st.IsAssembly_s(ref):
            for child in asm.children(ref):
                leaves(child, here, spools, bodies, spoolish)
        else:
            (spools if spoolish else bodies).append(asm.st.GetShape_s(ref).Moved(here))

    def walk(label, loc, depth=0):
        ref = asm.resolve(label)
        here = asm.place(label, loc)
        n = asm.name(label) or asm.name(ref)
        if "Hull" in n or "Tendon" in n:
            return
        if depth == 1 and "bottom_tower" not in n:
            leaves(label, loc, hand, hand)
            return
        if "XC-330-MotorAssembly" in n:
            key = centre(asm.st.GetShape_s(ref).Moved(here))
            if key not in motors:  # the export repeats some motors in place
                spools, bodies = [], []
                leaves(label, loc, spools, bodies)
                motors[key] = (spools, bodies)
            return
        if re.search(r"ForeArmStructure|SpoolHolder", n):
            leaves(label, loc, structure, structure)
            return
        if asm.st.IsAssembly_s(ref):
            for child in asm.children(ref):
                walk(child, here, depth + 1)

    for root in asm.roots():
        walk(root, TopLoc_Location())
    return structure, hand, motors


def merged(shapes, colour, reduction) -> trimesh.Trimesh | None:
    meshes = [m for m in (tessellate(s) for s in shapes) if m is not None]
    if not meshes:
        return None
    mesh = trimesh.util.concatenate(meshes)
    mesh.merge_vertices()
    if reduction and len(mesh.faces) > 2000:
        mesh = mesh.simplify_quadric_decimation(percent=reduction)
    mesh.apply_scale(0.001)
    mesh.visual.face_colors = colour
    return mesh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("side", choices=["right", "left"])
    parser.add_argument("step", help="that side's v2 base assembly STEP (Base_Right.step / Base_Left.step)")
    args = parser.parse_args()
    out = os.path.join(MODELS, args.side, "tower_spools.glb")

    structure, hand, motors = collect(Assembly(args.step))
    if len(motors) != 16:
        raise SystemExit(f"expected 16 finger motors, found {len(motors)}")
    xs = sorted({k[0] for k in motors})
    ys = sorted({k[1] for k in motors}, reverse=True)

    scene = trimesh.Scene()
    scene.add_geometry(merged(structure, [175, 180, 190, 255], TARGET_REDUCTION["structure"]),
                       node_name="structure", geom_name="structure")
    scene.add_geometry(merged(hand, [222, 224, 228, 255], TARGET_REDUCTION["hand"]),
                       node_name="hand", geom_name="hand")
    for (x, y, z), (spools, bodies) in sorted(motors.items()):
        pos = f"{'B' if z > 0 else 'F'}{xs.index(x) + 1}{ys.index(y) + 1}"
        for kind, shapes, colour in (("motor", bodies, [45, 47, 54, 255]),
                                     ("spool", spools, [235, 235, 235, 255])):
            mesh = merged(shapes, colour, TARGET_REDUCTION[kind])
            if mesh is not None:
                scene.add_geometry(mesh, node_name=f"{kind}_{pos}", geom_name=f"{kind}_{pos}")
    scene.export(out)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()

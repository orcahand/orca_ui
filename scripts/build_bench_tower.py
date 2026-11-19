"""Convert the bench tower's STEP into the GLB the bench page shows.

The STEP must name each motor slot ``mNN`` (``m01`` … ``m18``); the bench
turns those into motor numbers (``MOTOR_OF_PART`` in towerModel.ts).
Everything else is drawn as the tower.

    uv run --with cadquery-ocp python scripts/build_bench_tower.py \
        ~/Downloads/tower_main_gui.step
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.OCP.collections import (
    IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString as FileInfo,
    Sequence_TDF_Label as TDF_LabelSequence)
from OCP.Message import Message_ProgressRange
from OCP.RWGltf import RWGltf_CafWriter
from OCP.RWMesh import RWMesh_CoordinateSystem_Zup
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "bench" / "tower.glb"
SLOT = re.compile(r"^m(\d{2})(:\d+)?$")


def _name(label) -> str:
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--deflection", type=float, default=0.15, help="mesh tolerance, mm")
    args = parser.parse_args()

    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(args.step)) != IFSelect_RetDone or not reader.Transfer(doc):
        raise SystemExit(f"could not read {args.step}")

    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shapes.GetFreeShapes(roots)
    slots: list[str] = []
    for i in range(1, roots.Length() + 1):
        root = roots.Value(i)
        BRepMesh_IncrementalMesh(shapes.GetShape_s(root), args.deflection, False, 0.5, True)
        children = TDF_LabelSequence()
        shapes.GetComponents_s(root, children, False)
        slots += [n for j in range(1, children.Length() + 1)
                  if SLOT.match(n := _name(children.Value(j)))]
    if not slots:
        raise SystemExit("no component is named mNN — the bench would have no slots")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(args.out)), True)
    converter = writer.ChangeCoordinateSystemConverter()
    converter.SetInputLengthUnit(0.001)
    converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem_Zup)
    if not writer.Perform(doc, FileInfo(), Message_ProgressRange()):
        raise SystemExit(f"could not write {args.out}")
    print(f"{args.out}: {args.out.stat().st_size / 1e6:.2f} MB, "
          f"{len(slots)} slots ({', '.join(sorted(slots))})")


if __name__ == "__main__":
    main()

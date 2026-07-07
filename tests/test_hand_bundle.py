"""Sanity checks for the committed 3D hand asset bundle.

The bundle under ``orca_ui/models/hand_v2`` is produced by
``scripts/build_hand_bundle.py``; these tests skip when it hasn't been built.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

BUNDLE_DIR = Path(__file__).resolve().parent.parent / "orca_ui" / "models" / "hand_v2"
SIDES = [s for s in ("right", "left") if (BUNDLE_DIR / s / "hand.urdf").is_file()]
FINGERS = {"thumb", "index", "middle", "ring", "pinky"}

pytestmark = pytest.mark.skipif(
    not SIDES, reason="hand_v2 bundle not built (scripts/build_hand_bundle.py)")


def _core_joint_ids():
    import orca_core
    cfg = (Path(orca_core.__file__).resolve().parent
           / "models" / "v2" / "orcahand-right" / "config.yaml")
    if not cfg.is_file():
        pytest.skip(f"orca_core hand config not found at {cfg}")
    return set(yaml.safe_load(cfg.read_text())["joint_ids"])


@pytest.fixture(params=SIDES)
def side_dir(request):
    return BUNDLE_DIR / request.param


def test_urdf_parses_with_canonical_joints(side_dir):
    root = ET.parse(side_dir / "hand.urdf").getroot()
    revolute = {j.get("name") for j in root.findall("joint")
                if j.get("type") == "revolute"}
    assert revolute == _core_joint_ids()
    assert len(revolute) == 17


def test_urdf_has_fingertip_links(side_dir):
    root = ET.parse(side_dir / "hand.urdf").getroot()
    links = {l.get("name") for l in root.findall("link")}
    assert {f"{f}_fingertip" for f in FINGERS} <= links


def test_referenced_meshes_exist(side_dir):
    root = ET.parse(side_dir / "hand.urdf").getroot()
    refs = {m.get("filename") for m in root.iter("mesh")}
    assert refs, "URDF references no meshes"
    for ref in refs:
        assert (side_dir / ref).is_file(), f"missing mesh {ref}"
        # scale is baked into the GLB vertices by the build script
        assert ref.endswith(".glb")


def test_manifest_matches_core_joint_ids(side_dir):
    manifest = json.loads((side_dir / "manifest.json").read_text())
    assert set(manifest["joints"]) == _core_joint_ids()
    assert len(manifest["joints"]) == 17
    assert manifest["schema_version"] == 1
    for name, info in manifest["meshes"].items():
        assert info["tris"] > 0 and info["bytes"] > 0, name


def test_fingertips_yaml_has_five_fingers(side_dir):
    data = yaml.safe_load((side_dir / "fingertips.yaml").read_text())
    assert set(data) == FINGERS
    for finger, entry in data.items():
        assert entry["link"] == f"{finger}_fingertip"
        anchor = entry["anchor"]
        assert len(anchor) == 3
        assert all(isinstance(v, float) and abs(v) < 0.1 for v in anchor)


def test_joint_calibration_covers_all_joints():
    cal = yaml.safe_load((BUNDLE_DIR / "joint_calibration.yaml").read_text())
    ids = _core_joint_ids()
    assert ids <= set(cal)
    for jid in ids:
        entry = cal[jid]
        assert entry["sign"] in (1, -1)
        assert isinstance(entry["offset_deg"], (int, float))
        assert entry["evidence"] in {"rom_match", "rom_mirrored",
                                     "rom_mismatch", "ambiguous"}

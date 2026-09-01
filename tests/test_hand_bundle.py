"""Sanity checks for the committed 3D hand asset bundle.

The bundle under ``orca_ui/models/hand_v2`` is produced by
``scripts/build_hand_bundle.py``; these tests skip when it hasn't been built.
"""

import json
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


def test_manifest_matches_core_joint_ids(side_dir):
    manifest = json.loads((side_dir / "manifest.json").read_text())
    assert set(manifest["joints"]) == _core_joint_ids()
    assert len(manifest["joints"]) == 17
    assert manifest["schema_version"] == 1
    for name, info in manifest["meshes"].items():
        assert info["tris"] > 0 and info["bytes"] > 0, name

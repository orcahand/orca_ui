"""The board's hardware revision picks which joint-to-motor map a session runs.

orca_core decides this when a config is built, from the version the board
reports. The console loads hands by config_path, which skips orca_core's
detection, so the version it learned from the board has to be handed over
explicitly -- and before any hand is built, so every construction path sees
the same resolved config.
"""

import glob
import os
from types import SimpleNamespace

import orca_core
from orca_core.constants import HARDWARE_VERSION_V21
from orca_core.hand_config import OrcaHandConfig

from orca_ui.hand import sessions

MODELS = os.path.join(os.path.dirname(orca_core.__file__), "models", "v2")
LEFT = sorted(glob.glob(os.path.join(MODELS, "*-left", "config.yaml")))[0]
RIGHT = sorted(glob.glob(os.path.join(MODELS, "*-right", "config.yaml")))[0]
THUMB = {"thumb_mcp", "thumb_dip"}


def _presence(hw):
    return SimpleNamespace(detection=SimpleNamespace(identity=SimpleNamespace(hw_version=hw)))


def test_the_version_comes_from_the_board_identity():
    assert sessions._hardware_version_of(_presence(21)) == 21
    assert sessions._hardware_version_of(_presence(2)) == 2


def test_no_board_means_no_version():
    """A plain adapter has no board behind it, and discovery may not have run
    at all; neither must break the connect."""
    assert sessions._hardware_version_of(None) is None
    assert sessions._hardware_version_of(SimpleNamespace()) is None
    assert sessions._hardware_version_of(SimpleNamespace(detection=None)) is None
    assert sessions._hardware_version_of(
        SimpleNamespace(detection=SimpleNamespace(identity=None))) is None


def test_a_v21_board_puts_the_v21_map_in_force_on_a_left_hand():
    base = OrcaHandConfig.from_config_path(config_path=LEFT)
    resolved = sessions._for_hardware(base, _presence(HARDWARE_VERSION_V21))

    assert resolved.hardware_version == HARDWARE_VERSION_V21
    assert resolved.joint_to_motor_map == base.joint_to_motor_map
    differing = {j for j in base.joint_ids
                 if resolved.joint_inversion_dict[j] != base.joint_inversion_dict[j]}
    assert differing == THUMB


def test_a_v20_board_leaves_the_base_map():
    base = OrcaHandConfig.from_config_path(config_path=LEFT)
    resolved = sessions._for_hardware(base, _presence(2))
    assert resolved.hardware_version == 2
    assert resolved.joint_inversion_dict == base.joint_inversion_dict


def test_a_right_hand_is_untouched_whatever_the_board_says():
    base = OrcaHandConfig.from_config_path(config_path=RIGHT)
    resolved = sessions._for_hardware(base, _presence(HARDWARE_VERSION_V21))
    assert resolved.joint_inversion_dict == base.joint_inversion_dict


def test_an_unknown_version_returns_the_config_as_is():
    base = OrcaHandConfig.from_config_path(config_path=LEFT)
    assert sessions._for_hardware(base, None) is base


def test_a_pinned_version_wins_over_the_board_and_says_so(tmp_path, caplog):
    """The console hands the board's value in as detected, not as an override,
    so a config that pins the revision keeps the last word -- and the clash is
    logged, so a stale copied config is never mistaken for a detection bug."""
    import yaml
    with open(LEFT, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["hardware_version"] = HARDWARE_VERSION_V21
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    pinned = OrcaHandConfig.from_config_path(config_path=str(path))

    with caplog.at_level("WARNING"):
        resolved = sessions._for_hardware(pinned, _presence(2))
    assert resolved.hardware_version == HARDWARE_VERSION_V21
    assert "pins hardware_version=21" in caplog.text


def test_auto_takes_the_board(tmp_path):
    base = OrcaHandConfig.from_config_path(config_path=LEFT)   # packaged: auto
    assert base.hardware_version is None
    assert sessions._for_hardware(base, _presence(HARDWARE_VERSION_V21)).hardware_version == HARDWARE_VERSION_V21

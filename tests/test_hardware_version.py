"""The board's hardware revision picks which joint-to-motor map a session runs,
and the supervisor is the one place it is resolved: config.yaml's pin when it
has one, else what the board reported, installed before any hand is built and
re-applied (with a reconnect) when the pin changes.
"""

import glob
import os
import shutil

import orca_core
from orca_core.constants import HARDWARE_VERSION_V21
from orca_core.hand_config import OrcaHandConfig, _resolve_config_path, write_hardware_version

from orca_ui.hand.supervisor import HandSupervisor
from orca_ui.settings import UiSettings

MODELS = os.path.join(os.path.dirname(orca_core.__file__), "models", "v2")
LEFT = sorted(glob.glob(os.path.join(MODELS, "*-left", "config.yaml")))[0]
RIGHT = sorted(glob.glob(os.path.join(MODELS, "*-right", "config.yaml")))[0]
THUMB = {"thumb_mcp", "thumb_dip"}


def _supervisor(tmp_path, packaged):
    path = tmp_path / "config.yaml"
    shutil.copy(packaged, path)
    settings = UiSettings(config_path=str(path), mock=False, open_browser=False)
    return HandSupervisor(settings), str(path)


def test_a_v21_board_puts_the_v21_map_in_force_on_a_left_hand(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)
    base = sup.config
    assert sup._apply_hardware_version(HARDWARE_VERSION_V21)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21
    assert sup.config.joint_to_motor_map == base.joint_to_motor_map
    differing = {j for j in base.joint_ids
                 if sup.config.joint_inversion_dict[j] != base.joint_inversion_dict[j]}
    assert differing == THUMB
    assert sup.status().hardware_version == HARDWARE_VERSION_V21
    assert sup.status().board_hardware_version == HARDWARE_VERSION_V21
    assert not sup.status().hardware_version_pinned


def test_a_v20_board_leaves_the_base_map(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)
    base = sup.config
    sup._apply_hardware_version(2)
    assert sup.config.hardware_version == 2
    assert sup.config.joint_inversion_dict == base.joint_inversion_dict


def test_a_right_hand_keeps_its_map_whatever_the_board_says(tmp_path):
    sup, _ = _supervisor(tmp_path, RIGHT)
    base = sup.config
    sup._apply_hardware_version(HARDWARE_VERSION_V21)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21
    assert sup.config.joint_inversion_dict == base.joint_inversion_dict
    assert sup.config.uses_motor_travel, "the travel baseline applies to both sides"


def test_no_board_means_no_version(tmp_path):
    """A plain adapter has no board behind it; the config stays as loaded."""
    sup, _ = _supervisor(tmp_path, LEFT)
    base = sup.config
    assert not sup._apply_hardware_version(None)
    assert sup.config is base
    assert sup.status().hardware_version is None


def test_a_pinned_version_wins_over_the_board_and_says_so(tmp_path, caplog):
    sup, path = _supervisor(tmp_path, LEFT)
    write_hardware_version(path, HARDWARE_VERSION_V21)
    with caplog.at_level("WARNING"):
        sup._apply_hardware_version(2)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21
    assert sup.status().hardware_version_pinned
    assert "pins hardware_version=21" in caplog.text


def test_auto_takes_the_board(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)   # packaged: auto
    assert sup.config.hardware_version is None
    sup._apply_hardware_version(HARDWARE_VERSION_V21)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21


def test_the_pin_is_in_force_straight_from_the_file(tmp_path):
    """A hand loaded by path, not through load_hand, still gets the pinned map."""
    sup, path = _supervisor(tmp_path, LEFT)
    write_hardware_version(path, HARDWARE_VERSION_V21)
    pinned = OrcaHandConfig.from_config_path(config_path=path)
    base = OrcaHandConfig.from_config_path(config_path=LEFT)
    assert {j for j in base.joint_ids if pinned.joint_inversion_dict[j] != base.joint_inversion_dict[j]} == THUMB

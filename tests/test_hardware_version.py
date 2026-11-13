"""The board's hardware revision picks which joint-to-motor map a session runs,
and the supervisor is the one place it is resolved: the version chosen in the
console for this session, else what the board reported, installed before any
hand is built and re-applied (with a reconnect) when the choice changes. A
choice is never written anywhere and never follows the console to another hand.
"""

import glob
import os
from types import SimpleNamespace

import orca_core
from orca_core.constants import HARDWARE_VERSION_V21

from orca_ui.hand.supervisor import HandSupervisor
from orca_ui.settings import UiSettings

MODELS = os.path.join(os.path.dirname(orca_core.__file__), "models", "v2")
LEFT = sorted(glob.glob(os.path.join(MODELS, "*-left", "config.yaml")))[0]
RIGHT = sorted(glob.glob(os.path.join(MODELS, "*-right", "config.yaml")))[0]
THUMB = {"thumb_mcp", "thumb_dip"}


def _supervisor(tmp_path, packaged):
    path = orca_core.write_standalone_config(str(tmp_path / "config.yaml"), packaged)
    settings = UiSettings(config_path=path, mock=False, open_browser=False)
    return HandSupervisor(settings), path


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
    assert sup.status().hardware_version_override is None


def test_a_v20_board_leaves_the_base_map(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)
    base = sup.config
    sup._apply_hardware_version(2)
    assert sup.config.hardware_version == 200
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


def test_a_session_choice_wins_over_the_board_and_writes_nothing(tmp_path):
    sup, path = _supervisor(tmp_path, LEFT)
    before = sorted(p.name for p in tmp_path.iterdir()), open(path).read()
    sup._apply_hardware_version(2)
    sup.set_hardware_version(HARDWARE_VERSION_V21)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21
    assert sup.status().hardware_version_override == HARDWARE_VERSION_V21
    assert sup.status().board_hardware_version == 200
    sup.set_hardware_version(None)
    assert sup.config.hardware_version == 200
    assert (sorted(p.name for p in tmp_path.iterdir()), open(path).read()) == before


def test_another_hand_connecting_drops_the_choice(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)
    sup._identity = SimpleNamespace(serial="ser-1", board_id=None)
    sup.set_hardware_version(HARDWARE_VERSION_V21)
    sup._identity = None                          # detection missed the identity once
    assert not sup._forget_override_of_another_hand("ser-1")   # the connect got it
    assert sup.hardware_version_override == HARDWARE_VERSION_V21
    assert sup._forget_override_of_another_hand("ser-2")
    sup._apply_hardware_version(2)
    assert sup.hardware_version_override is None
    assert sup.config.hardware_version == 200


def test_auto_takes_the_board(tmp_path):
    sup, _ = _supervisor(tmp_path, LEFT)   # packaged: auto
    assert sup.config.hardware_version is None
    sup._apply_hardware_version(HARDWARE_VERSION_V21)
    assert sup.config.hardware_version == HARDWARE_VERSION_V21

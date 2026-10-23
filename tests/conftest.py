"""Suite-wide fixtures."""

import os

import pytest
from orca_core import hand_config

from orca_ui.hand.operations import player


@pytest.fixture(autouse=True)
def _no_sidecar_from_the_installed_package(monkeypatch):
    """A packaged model carries no local_config.yaml during tests.

    The console's picker writes a hand's pin beside the installed package's
    config.yaml, so a bench pin would otherwise reach every test that loads a
    packaged model. Sidecars beside copies in tmp_path still apply.
    """
    package_dir = os.path.dirname(os.path.abspath(hand_config.__file__))
    read = hand_config.read_local_config

    def read_outside_package(config_path):
        if os.path.abspath(config_path).startswith(package_dir + os.sep):
            return {}
        return read(config_path)

    monkeypatch.setattr(hand_config, "read_local_config", read_outside_package)


@pytest.fixture(autouse=True)
def _calibrations_register_is_never_the_real_one(tmp_path_factory, monkeypatch):
    """No test reads or writes the hand calibrations kept on this machine.

    A session names the hand it is driving and then reads and writes that
    hand's file. Pointed at the real register, a test would hand a mock hand
    somebody's calibration -- and write the mock's own back over it.
    """
    from orca_core import board_store

    monkeypatch.setenv(board_store.CALIBRATIONS_DIR_ENV,
                       str(tmp_path_factory.mktemp("calibrations")))


@pytest.fixture(autouse=True, scope="session")
def _brisk_playback_pacing():
    """Scale the player's human-watchable pacing down 4x.

    Nothing asserts on the speed itself; test_playback derives its frame
    counts from these constants. 4x keeps the shortest phase the suite polls
    for (the approach glide, about 0.2 s at 20 ms polls) observable; faster
    and those tests pass without seeing it.
    """
    player.WAYPOINT_SPEED_DEG_S = 240.0    # 60
    player.MIN_SEGMENT_S = 0.08            # 0.3
    yield

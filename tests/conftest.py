"""Suite-wide fixtures."""

import pytest
from orca_core import hardware_hand

from orca_ui.hand.operations import player


@pytest.fixture(autouse=True, scope="session")
def _no_serial_settle_for_mocks():
    """Drop orca_core's torque-disable settle — a mock hand has no port to settle."""
    hardware_hand.MOTOR_TORQUE_DISABLE_SETTLE_S = 0.0
    yield


@pytest.fixture(autouse=True, scope="session")
def _brisk_playback_pacing():
    """Scale the player's human-watchable pacing down 4x.

    Nothing asserts on the speed itself. 4x is measured, not chosen: at 10x the
    waypoint holds start expiring before the hand arrives, so they pass without
    testing arrival. Re-measure before going further.
    """
    player.WAYPOINT_SPEED_DEG_S = 240.0    # 60
    player.MIN_SEGMENT_S = 0.08            # 0.3
    yield

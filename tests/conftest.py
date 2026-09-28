"""Suite-wide fixtures."""

import pytest

from orca_ui.hand.operations import player


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

"""Suite-wide fixtures."""

import pytest

from orca_ui.hand.operations import player


@pytest.fixture(autouse=True)
def _orca_home_in_tmp(tmp_path_factory, monkeypatch):
    """No test reads or writes the real ~/.orca: the console's own state and
    orca_core's hand store both live under ORCA_HOME. Mock hands get a folder
    of their own per test (orca_core keeps one per process)."""
    from orca_core import hand_store

    monkeypatch.setenv("ORCA_HOME", str(tmp_path_factory.mktemp("orca-home")))
    monkeypatch.setattr(hand_store, "_mock_root", tmp_path_factory.mktemp("mock-hands"))


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

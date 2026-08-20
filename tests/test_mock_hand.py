"""End-to-end tests for the --mock hand: production clients over mock links.

These exercise the real TactileClient / JointEncoderClient / JointLoopThread
stack against the orca_ui pumps and responder — the same path the UI uses.
"""

import time

import pytest
import yaml

from orca_ui.mock import build_mock_hand, materialize_mock_model

FINGERS = {"thumb", "index", "middle", "ring", "pinky"}


def _wait_for(predicate, timeout=3.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def full_hand():
    hand = build_mock_hand(materialize_mock_model())
    ok, msg = hand.connect()
    assert ok, msg
    try:
        yield hand
    finally:
        hand.disconnect()


def test_tactile_configuration_reports_all_sensors(full_hand):
    cfg = full_hand.get_tactile_configuration()
    assert cfg is not None
    assert set(cfg.active_sensors) == FINGERS
    assert cfg.num_taxels["index"] == 87
    assert cfg.num_taxels["thumb"] == 51


def test_tactile_stream_delivers_combined_frames(full_hand):
    full_hand.start_tactile_stream(resultant=True, taxels=True)
    reading = _wait_for(full_hand.get_tactile_data)
    assert reading is not None
    assert set(reading.forces.fingers) == FINGERS
    assert len(reading.taxels["index"]) == 87
    assert len(reading.forces["thumb"]) == 3


def test_measured_joints_track_initial_pose(full_hand):
    measured = _wait_for(full_hand.get_measured_joints)
    assert measured is not None
    assert len(measured) == 17  # every encoder slot, wrist included
    # Mock motors start at 0 rad, which the mock calibration maps to 0 deg.
    for joint, angle in measured.items():
        assert abs(angle) < 1.0, f"{joint} starts at {angle:.2f} deg"


def test_loop_converges_on_commanded_target(full_hand):
    full_hand.enable_torque()
    full_hand.set_joint_positions({"index_mcp": 40.0})

    def close_enough():
        measured = full_hand.get_measured_joints() or {}
        return abs(measured.get("index_mcp", 0.0) - 40.0) < 2.0

    assert _wait_for(close_enough), (
        f"index_mcp did not converge: {full_hand.get_measured_joints()}"
    )


def test_loop_stats_report_healthy_loop(full_hand):
    assert _wait_for(lambda: full_hand.get_loop_stats()["cycles_ok"] > 0)
    assert not full_hand.get_loop_stats()["fallback_active"]


@pytest.mark.parametrize("strip", ["sensors", "feedback"])
def test_reduced_capability_configs_select_lesser_classes(tmp_path, strip):
    from orca_core import OrcaHandJointFeedback, OrcaHandTouch

    config_path = materialize_mock_model()
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if strip == "sensors":
        del raw["sensors"]
    else:
        raw["use_joint_feedback"] = False
        raw["joint_encoder_joints"] = None
    stripped = tmp_path / "config.yaml"
    stripped.write_text(yaml.safe_dump(raw, sort_keys=False))
    import shutil
    import os
    shutil.copy(os.path.join(os.path.dirname(config_path), "calibration.yaml"),
                tmp_path / "calibration.yaml")

    hand = build_mock_hand(str(stripped))
    ok, msg = hand.connect()
    assert ok, msg
    try:
        if strip == "sensors":
            assert isinstance(hand, OrcaHandJointFeedback)
            assert not isinstance(hand, OrcaHandTouch)
            assert _wait_for(hand.get_measured_joints)
        else:
            assert isinstance(hand, OrcaHandTouch)
            assert not isinstance(hand, OrcaHandJointFeedback)
            hand.start_tactile_stream(resultant=True, taxels=False)
            assert _wait_for(hand.get_tactile_forces) is not None
    finally:
        hand.disconnect()


@pytest.mark.parametrize("side", ["right", "left"])
def test_measured_joints_start_at_rest_on_both_sides(tmp_path, side):
    """The encoder pump must encode with the same per-side polarity table
    orca_core decodes with. The mirrored assembly flips the abduction axes,
    so encoding a left hand with the right-hand signs decoded those six
    joints as (2 * rom_upper - angle) — every abd joint pinned at its ROM
    limit, rendering the hand as a splayed claw.
    """
    import os
    import shutil

    config_path = materialize_mock_model()
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    raw["type"] = side
    sided = tmp_path / "config.yaml"
    sided.write_text(yaml.safe_dump(raw, sort_keys=False))
    shutil.copy(os.path.join(os.path.dirname(config_path), "calibration.yaml"),
                tmp_path / "calibration.yaml")

    hand = build_mock_hand(str(sided))
    ok, msg = hand.connect()
    assert ok, msg
    try:
        measured = _wait_for(hand.get_measured_joints)
        assert measured is not None
        assert len(measured) == 17
        for joint, angle in measured.items():
            assert abs(angle) < 1.0, f"{side} {joint} starts at {angle:.2f} deg"
    finally:
        hand.disconnect()

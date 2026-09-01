"""End-to-end tests for the --mock hand: production clients over mock links.

These exercise the real TactileClient / JointEncoderClient / JointLoopThread
stack against the orca_ui pumps and responder — the same path the UI uses.
"""

import time

import pytest

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


def test_loop_converges_on_commanded_target(full_hand):
    full_hand.enable_torque()
    full_hand.set_joint_positions({"index_mcp": 40.0})

    def close_enough():
        measured = full_hand.get_measured_joints() or {}
        return abs(measured.get("index_mcp", 0.0) - 40.0) < 2.0

    assert _wait_for(close_enough), (
        f"index_mcp did not converge: {full_hand.get_measured_joints()}"
    )

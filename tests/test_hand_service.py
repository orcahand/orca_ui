"""HandService + supervisor tests: mock end-to-end and ladder unit tests."""

import time

import pytest

from orca_ui.hand.service import HandService, ServiceError
from orca_ui.mock import materialize_mock_model
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def service():
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False)
    statuses: list[dict] = []
    errors: list[str] = []
    svc = HandService(settings, publish_status=statuses.append,
                      publish_error=errors.append)
    svc._test_statuses = statuses
    svc._test_errors = errors
    svc.start()
    assert _wait_for(lambda: svc.status()["state"] == "connected"), svc.status()
    try:
        yield svc
    finally:
        svc.stop()


def test_autoconnect_reports_full_capabilities(service):
    status = service.status()
    caps = status["capabilities"]
    assert caps["motors"] and caps["tactile"] and caps["encoders"]
    assert caps["feedback_loop"] and not caps["degraded"]
    assert status["torque_enabled"] is False  # never auto-enabled


def test_tactile_stream_autostarts(service):
    assert _wait_for(lambda: service.session.tactile_data() is not None)


def test_hand_info_shape(service):
    info = service.hand_info()
    assert info["side"] == "right"
    assert len(info["joints"]) == 17
    index_mcp = next(j for j in info["joints"] if j["id"] == "index_mcp")
    assert index_mcp["rom"] == [-25.0, 100.0]
    assert index_mcp["encoder_backed"] is True
    wrist = next(j for j in info["joints"] if j["id"] == "wrist")
    assert wrist["encoder_backed"] is True
    assert info["control"]["tactile_mode"] == "combined"


def test_targets_require_torque(service):
    with pytest.raises(ServiceError) as exc:
        service.set_targets({"index_mcp": 30.0})
    assert exc.value.status_code == 409


def test_torque_enable_then_targets_converge(service):
    seed = service.enable_torque()["seed"]
    assert "index_mcp" in seed
    assert service.status()["torque_enabled"] is True

    service.set_targets({"index_mcp": 40.0})

    def converged():
        measured = service.session.measured_joints() or {}
        return abs(measured.get("index_mcp", 0.0) - 40.0) < 2.0

    assert _wait_for(converged), service.session.measured_joints()

    service.disable_torque()
    assert service.status()["torque_enabled"] is False


def test_unknown_joint_rejected(service):
    service.enable_torque()
    with pytest.raises(ServiceError):
        service.set_targets({"nonexistent_joint": 1.0})


def test_gains_and_mode_roundtrip(service):
    service.set_gains(kp=2.0, ki=6.0, correction_max_deg=30.0)
    service.set_max_current(400)
    state = service.control_state()
    assert state["gains"]["kp"] == 2.0
    assert state["max_current"] == 400

    service.set_tactile_mode("taxels")
    assert service.tactile_mode == "taxels"

    def has_taxels():
        reading = service.session.tactile_data()
        return reading is not None and reading.taxels

    assert _wait_for(has_taxels)


def test_per_joint_gains_are_read_back_from_the_controller(service):
    loop_joints = service.session.hand.loop_joint_names
    assert "wrist" in loop_joints, "the wrist is a loop joint like any other"
    tuned = loop_joints[0]
    config_gains = service.control_state()["config_gains"]

    service.set_gains(kp=2.0, ki=6.0, correction_max_deg=30.0)
    service.set_gains(kp=5.0, ki=1.0, correction_max_deg=10.0, joints=[tuned])

    state = service.control_state()
    assert state["gains"] is None                    # no longer uniform
    assert state["joint_gains"][tuned]["kp"] == 5.0
    assert all(state["joint_gains"][j]["kp"] == 2.0
               for j in loop_joints if j != tuned)

    # control_state reports what the controller runs, not a UI shadow copy.
    controller = service.session.hand._controller
    assert controller._Kp[loop_joints.index(tuned)] == 5.0

    entry = next(j for j in service.gains_state()["joints"]
                 if j["joint"] == tuned)
    assert entry["modified"] is True and entry["kp"] == 5.0

    service.reset_gains()
    assert service.control_state()["joint_gains"] == config_gains


def test_gains_reject_joints_outside_the_loop(service):
    before = service.control_state()["joint_gains"]
    with pytest.raises(ServiceError):
        service.set_gains(kp=1.0, ki=1.0, correction_max_deg=10.0,
                          joints=["nonexistent_joint"])
    assert service.control_state()["joint_gains"] == before


def test_stats_shape(service):
    time.sleep(0.3)
    stats = service.stats()
    assert stats["loop"]["cycles_ok"] > 0
    assert stats["encoder"]["frames_ok"] > 0


def test_wrist_is_measured_and_follows_commands(service):
    """The wrist is a closed-loop joint: sensed, and driven by the loop."""
    measured = _wait_for(service.session.measured_joints) or {}
    assert "wrist" in measured
    assert len(measured) == 17

    service.enable_torque()
    service.set_targets({"wrist": 20.0})

    def wrist_tracks():
        angles = service.session.measured_joints() or {}
        return abs(angles.get("wrist", 0.0) - 20.0) < 0.5

    assert _wait_for(wrist_tracks), service.session.measured_joints()


def test_direct_motor_mode_gating_and_moves(service):
    snapshot = service.motor_snapshot()
    assert snapshot["direct_mode"] is False
    assert snapshot["motors"], "expected configured motors"
    motor = snapshot["motors"][0]

    service.enable_torque()

    # Writes are refused until the mode is armed.
    with pytest.raises(ServiceError, match="not armed"):
        service.set_motor_position(motor["id"], motor["position"] + 0.1)

    service.set_direct_motor_mode(True)
    assert service.control_state()["direct_motor_mode"] is True

    # Joint targets are suspended while armed.
    with pytest.raises(ServiceError, match="direct motor mode"):
        service.set_targets({"index_mcp": 10.0})

    # A small move lands; an implausible jump is rejected.
    moved = service.set_motor_position(motor["id"], motor["position"] + 0.1)
    assert moved["position"] == pytest.approx(motor["position"] + 0.1)
    with pytest.raises(ServiceError, match="capped"):
        service.set_motor_position(motor["id"], moved["position"] + 5.0)

    # Disarm restores normal joint control.
    service.set_direct_motor_mode(False)
    assert service.control_state()["direct_motor_mode"] is False
    service.set_targets({"index_mcp": 10.0})


def test_hand_info_reports_encoder_calibration_state(service):
    info = service.hand_info()
    loop_joints = set(service.session.hand.loop_joint_names or [])
    for joint in info["joints"]:
        if joint["encoder_backed"]:
            assert joint["encoder_calibrated"] is True  # mock model is complete
        else:
            assert joint["encoder_calibrated"] is None
        # loop_controlled: True for loop joints, None for joints with no
        # encoder to close on; False only for connect-time skips, which the
        # complete mock model never has.
        if joint["id"] in loop_joints:
            assert joint["loop_controlled"] is True
        else:
            assert joint["loop_controlled"] is None


def test_encoder_sensed_joints_match_orca_core(service):
    """The UI's config-only mirror must not drift from orca_core's list."""
    from orca_ui.hand.service import _encoder_sensed_joints

    assert (_encoder_sensed_joints(service.supervisor.config)
            == service.session.hand.encoder_backed_joints)


def test_fully_calibrated_hand_offers_no_recalibration_hint(service):
    calibration = service.hand_info()["calibration"]
    assert calibration["motors"] is True
    assert calibration["joint_feedback"] is True
    assert calibration["missing_anchors"] == []
    assert calibration["hint"] is None


def test_missing_anchor_is_reported_with_a_recalibration_hint(service):
    """A calibration made before the wrist joined the loop has no wrist
    anchor: the motors are still calibrated and the hint names the joint."""
    import dataclasses

    hand = service.session.hand
    anchors = dict(hand.calibration.joint_encoder_calibration_dict)
    anchors.pop("wrist")
    hand.calibration = dataclasses.replace(
        hand.calibration, joint_encoder_calibration_dict=anchors)

    calibration = service.hand_info()["calibration"]
    assert calibration["motors"] is True
    assert calibration["joint_feedback"] is False
    assert calibration["missing_anchors"] == ["wrist"]
    assert "wrist" in calibration["hint"]


# ----- calibration prompts ---------------------------------------------------------------


class _FakeHand:
    def __init__(self, calibrated, joint_ids, anchors):
        self._calibrated = calibrated
        self.config = type("C", (), {"joint_ids": joint_ids})()
        self.calibration = type(
            "Cal", (), {"joint_encoder_calibration_dict": anchors})()

    def is_calibrated(self, use_joint_feedback=False):
        return self._calibrated


class _FakeSession:
    def __init__(self, hand):
        self.hand = hand
        self.caps = type("Caps", (), {"motors": True})()


def _calibration(service, *, calibrated, anchors, encoder_backed=("index_mcp", "wrist")):
    joints = ["index_mcp", "wrist"]
    session = _FakeSession(_FakeHand(calibrated, joints, dict.fromkeys(anchors)))
    return service._calibration_state(session, set(encoder_backed), set(anchors))


def test_fully_uncalibrated_hand_asks_to_be_calibrated(service):
    """The worst case used to report hint=None: the connect ladder has already
    dropped joint sensing and nothing on screen said why."""
    state = _calibration(service, calibrated=False, anchors=())
    assert state["motors"] is False
    assert state["needs_calibration"] is True
    assert "not calibrated" in state["hint"]
    assert "Calibrate" in state["hint"]


def test_missing_anchors_still_name_the_joints(service):
    state = _calibration(service, calibrated=True, anchors=("index_mcp",))
    assert state["needs_calibration"] is True
    assert state["missing_anchors"] == ["wrist"]
    assert "wrist" in state["hint"]
    assert state["joint_feedback"] is False


def test_calibrated_hand_asks_for_nothing(service):
    state = _calibration(service, calibrated=True, anchors=("index_mcp", "wrist"))
    assert state["needs_calibration"] is False
    assert state["hint"] is None
    assert state["joint_feedback"] is True


def test_uncalibrated_hand_without_encoders_does_not_mention_anchors(service):
    state = _calibration(service, calibrated=False, anchors=(), encoder_backed=())
    assert state["needs_calibration"] is True
    assert "anchor" not in state["hint"]


def test_no_motor_bus_asks_for_nothing(service):
    """Calibration needs motors; prompting a motorless session is noise."""
    session = _FakeSession(_FakeHand(False, ["index_mcp"], {}))
    session.caps = type("Caps", (), {"motors": False})()
    state = service._calibration_state(session, {"index_mcp"}, set())
    assert state["needs_calibration"] is False
    assert state["hint"] is None

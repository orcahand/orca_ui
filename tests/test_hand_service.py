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
    assert wrist["encoder_backed"] is True  # slot 16 is sensed (loop-excluded only)
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


def test_per_joint_gain_overrides(service):
    loop_joints = service.session.hand.loop_joint_names
    assert loop_joints, "mock hand should close the loop on its joints"
    tuned = loop_joints[0]

    service.set_gains(kp=2.0, ki=6.0, correction_max_deg=30.0)
    service.set_gains(kp=5.0, ki=1.0, correction_max_deg=10.0, i_clamp_deg=4.0,
                      joints=[tuned])

    state = service.control_state()
    assert state["gains"]["kp"] == 2.0          # baseline untouched
    assert state["joint_gains"][tuned]["kp"] == 5.0

    # The controller carries one channel per loop joint: the tuned joint's
    # gains differ from the baseline every other channel still runs.
    controller = service.session.hand._controller
    index = loop_joints.index(tuned)
    assert controller._Kp[index] == 5.0
    assert controller._i_clamp_deg[index] == 4.0
    others = [i for i in range(len(loop_joints)) if i != index]
    assert all(controller._Kp[i] == 2.0 for i in others)
    assert all(controller._i_clamp_deg[i] == 30.0 for i in others)

    gains = service.gains_state()
    assert gains["baseline"]["kp"] == 2.0
    assert len(gains["joints"]) == len(loop_joints)
    entry = next(j for j in gains["joints"] if j["joint"] == tuned)
    assert entry["source"] == "override" and entry["kp"] == 5.0
    # Joints outside the loop (wrist and friends) have no gains to set.
    assert "wrist" in gains["open_loop_joints"]

    service.clear_joint_gains([tuned])
    assert service.control_state()["joint_gains"] == {}
    assert service.session.hand._controller._Kp[index] == 2.0


def test_gains_reject_joints_outside_the_loop(service):
    with pytest.raises(ServiceError):
        service.set_gains(kp=1.0, ki=1.0, correction_max_deg=10.0,
                          joints=["wrist"])
    assert service.control_state()["joint_gains"] == {}


def test_stats_shape(service):
    time.sleep(0.3)
    stats = service.stats()
    assert stats["loop"]["cycles_ok"] > 0
    assert stats["encoder"]["frames_ok"] > 0


def test_wrist_is_measured_and_follows_commands(service):
    """The wrist encoder (slot 16) is sensed even though it stays outside
    orca_core's closed loop — measured must include it and track commands."""
    measured = _wait_for(service.session.measured_joints) or {}
    assert "wrist" in measured
    assert len(measured) == 17

    service.enable_torque()
    service.set_targets({"wrist": 20.0})

    def wrist_tracks():
        estimate = service.session.estimate_joints() or {}
        angles = service.session.measured_joints() or {}
        return (abs(estimate.get("wrist", 0.0) - 20.0) < 1.0
                and abs(angles.get("wrist", 0.0) - 20.0) < 2.0)

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
        # loop_controlled: True for loop joints, None for everything the loop
        # doesn't target by design (wrist, non-encoder joints); False only
        # for connect-time skips, which the complete mock model never has.
        if joint["id"] in loop_joints:
            assert joint["loop_controlled"] is True
        else:
            assert joint["loop_controlled"] is None

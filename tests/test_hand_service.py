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
    assert index_mcp["rom"] == [-60.0, 100.0]
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


def test_hand_info_reports_encoder_calibration_state(service):
    info = service.hand_info()
    for joint in info["joints"]:
        if joint["encoder_backed"]:
            assert joint["encoder_calibrated"] is True  # mock model is complete
        else:
            assert joint["encoder_calibrated"] is None

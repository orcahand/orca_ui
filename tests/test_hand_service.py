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


def test_max_current_floor_is_the_calibration_current(service):
    """orca_core refuses a ceiling below the calibration current. The floor is
    published so the UI can stop there, and a write below it is rejected
    BEFORE the hardware is touched — a half-applied ceiling would leave the
    motors and the config disagreeing."""
    state = service.control_state()
    floor = state["max_current_floor"]
    assert floor == service.supervisor.config.calibration_current
    assert state["max_current"] >= floor

    before = service.control_state()["max_current"]
    with pytest.raises(ServiceError) as excinfo:
        service.set_max_current(floor - 1)
    assert str(floor) in str(excinfo.value)
    # Nothing moved: not our snapshot, not the hand's config.
    assert service.control_state()["max_current"] == before
    assert service.session.hand.config.max_current == before

    service.set_max_current(floor)
    assert service.control_state()["max_current"] == floor

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


# ----- calibration prompts ---------------------------------------------------------------
#
# _calibration_state never touches self, so these drive it on an unstarted
# service: no mock hand, no supervisor threads, no connect wait.


@pytest.fixture(scope="module")
def calibration_state():
    """``_calibration_state`` bound to a service that was never started."""
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False)
    return HandService(settings, publish_status=lambda _: None,
                       publish_error=lambda _: None)._calibration_state


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


def _calibration(calibration_state, *, calibrated, anchors,
                 encoder_backed=("index_mcp", "wrist")):
    joints = ["index_mcp", "wrist"]
    session = _FakeSession(_FakeHand(calibrated, joints, dict.fromkeys(anchors)))
    return calibration_state(session, set(encoder_backed), set(anchors))

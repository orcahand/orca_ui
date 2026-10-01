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
    # The rejection names the value that was refused and quotes orca_core's
    # reason, so the operator is not left guessing which limit bit.
    assert str(floor - 1) in str(excinfo.value)
    assert "calibration current" in str(excinfo.value)
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


def test_enabling_torque_applies_the_current_ceiling(service):
    """The console never calls init_joints, which is what writes Goal Current
    on the scripted paths. Without this the motors keep the ceiling they
    powered up with while the panel reports the configured one."""
    hand = service.supervisor.session.hand
    applied: list[int] = []
    hand.set_max_current = applied.append

    service.enable_torque()

    assert applied == [service._max_current]


def test_a_ceiling_write_that_fails_still_lets_torque_come_on(service):
    """A hand that will not take the ceiling is still a hand the operator has
    to be able to energize and move out of the way."""
    hand = service.supervisor.session.hand

    def boom(_ma):
        raise OSError("bus busy")

    hand.set_max_current = boom

    assert service.enable_torque()["seed"]
    assert service.status()["torque_enabled"] is True


def test_servo_gains_round_trip(service):
    """The panel must show what the motors hold, so a write is followed by a
    read-back rather than echoing the request."""
    before = service.read_servo_gains()
    assert "1" in before and before["1"]["kp"] is not None

    after = service.set_servo_gains(1, {"kp": 1234, "ki": None, "kd": None,
                                        "ff_1st": None, "ff_2nd": None})
    assert after["1"]["kp"] == 1234
    # Fields not named keep their previous values.
    assert after["1"]["kd"] == before["1"]["kd"]


def test_enabling_torque_reapplies_only_gains_the_operator_chose(service):
    """Gains are RAM and a power cycle clears them. Motors nobody tuned must
    not be handed our idea of a default."""
    applied = []
    hand = service.supervisor.session.hand
    hand.set_servo_gains = applied.append

    service.enable_torque()
    assert applied == []            # nothing chosen yet

    hand.set_servo_gains = lambda g: None
    service.set_servo_gains(2, {"kp": 900, "ki": None, "kd": None,
                                "ff_1st": None, "ff_2nd": None})
    hand.set_servo_gains = applied.append
    service.disable_torque()
    service.enable_torque()

    assert len(applied) == 1 and set(applied[0]) == {2}


def test_servo_profile_round_trip_and_reapply(service):
    """Profile limits are RAM like gains, so the same rules apply: read back
    from the motors, and re-apply only what the operator chose."""
    # Connecting leaves a usable profile rather than none: without one a goal
    # position is a step command the servo chases as fast as it can.
    before = service.read_servo_profile()
    assert before["1"]["velocity_rad_s"] > 0.0
    client = service.supervisor.session.hand.motor_client
    ceiling = client.read_profile_limits([1])[1].velocity_rad_s
    assert before["1"]["velocity_rad_s"] < ceiling

    after = service.set_servo_profile(
        1, {"velocity_rad_s": 2.5, "acceleration_rad_s2": None})
    assert after["1"]["velocity_rad_s"] == 2.5
    assert (after["1"]["acceleration_rad_s2"]
            == before["1"]["acceleration_rad_s2"])  # untouched

    applied = []
    hand = service.supervisor.session.hand
    hand.set_servo_profile = applied.append
    service.disable_torque()
    service.enable_torque()
    assert len(applied) == 1 and set(applied[0]) == {1}


def test_pose_source_auto_follows_the_torque_state(service):
    """Derived on every read rather than latched, so anything that drops
    torque -- e-stop included -- reverts the model within one tick."""
    assert service.effective_pose_source() == "estimate"
    service.enable_torque()
    assert service.effective_pose_source() == "target"
    service.disable_torque()
    assert service.effective_pose_source() == "estimate"


def test_pinned_pose_sources_ignore_torque(service):
    service.set_pose_source("estimate")
    service.enable_torque()
    assert service.effective_pose_source() == "estimate"

    service.set_pose_source("target")
    service.disable_torque()
    assert service.effective_pose_source() == "target"

    service.set_pose_source("auto")
    assert service.effective_pose_source() == "estimate"


def test_control_state_carries_both_the_mode_and_what_it_resolved_to(service):
    state = service.control_state()
    assert state["pose_source"] == "auto"
    assert state["effective_pose_source"] == "estimate"
    with pytest.raises(ServiceError):
        service.set_pose_source("nonsense")


def test_targets_are_clamped_to_the_rom_before_anything_sees_them(service):
    """The echo, the interpolator and adherence tracking must agree on what
    the hand is sent, so the clamp happens here, not deep in orca_core."""
    service.enable_torque()
    rom = service.supervisor.config.joint_roms_dict["index_mcp"]
    service.set_targets({"index_mcp": float(rom[1]) + 500.0})
    assert service._targets["index_mcp"] == float(rom[1])
    assert service.worker._to["index_mcp"] == float(rom[1])


def test_servo_writes_are_refused_on_a_family_without_the_registers(service, monkeypatch):
    """orca_core ignores the write and logs; the console must say so with a
    501 instead of storing values the motors never held."""
    from types import SimpleNamespace

    hand = SimpleNamespace(
        config=service.supervisor.config,
        get_servo_gains=lambda: {m: None for m in service.supervisor.config.motor_ids},
        set_servo_gains=lambda gains: None,
        get_servo_profile=lambda: {m: None for m in service.supervisor.config.motor_ids},
        set_servo_profile=lambda profiles: None,
    )
    monkeypatch.setattr(service, "_require_motors", lambda: SimpleNamespace(hand=hand))
    motor = service.supervisor.config.motor_ids[0]
    with pytest.raises(ServiceError) as excinfo:
        service.set_servo_gains(motor, {"kp": 800})
    assert excinfo.value.status_code == 501
    with pytest.raises(ServiceError) as excinfo:
        service.set_servo_profile(motor, {"velocity_rad_s": 1.0})
    assert excinfo.value.status_code == 501
    assert service._servo_gains == {} and service._servo_profiles == {}


def test_reboot_needs_torque_off_and_reports_an_unanswered_read_back(service, monkeypatch):
    service.enable_torque()
    motor = service.supervisor.config.motor_ids[0]
    with pytest.raises(ServiceError) as excinfo:
        service.reboot_motor(motor)
    assert excinfo.value.status_code == 409
    service.disable_torque()

    client = service.session.hand.motor_client
    monkeypatch.setattr(type(client), "reboot_motor", lambda self, mid: None, raising=False)
    monkeypatch.setattr(type(client), "read_hardware_error", lambda self, mid: None)
    monkeypatch.setattr("orca_ui.hand.service.MOTOR_REBOOT_SETTLE_S", 0.0)
    result = service.reboot_motor(motor)
    assert result["cleared"] is None and result["read_back"] is False

    monkeypatch.setattr(type(client), "read_hardware_error", lambda self, mid: 0)
    result = service.reboot_motor(motor)
    assert result["cleared"] is True and result["read_back"] is True


def test_hand_info_says_whether_the_family_can_reboot(service):
    info = service.hand_info()
    client = service.session.hand.motor_client
    assert info["reboot_supported"] == hasattr(client, "reboot_motor")


def test_a_touch_tier_with_no_answering_sensor_falls_to_the_next_tier(monkeypatch):
    """A tactile board with nothing on its sensor slots connects, then fails
    the moment a stream starts. The ladder must not call that a touch hand."""
    from types import SimpleNamespace

    from orca_core import HandDetection
    from orca_core.hardware.sensing.serial_discovery import OrcaBoardInfo

    from orca_ui.hand import sessions
    from orca_ui.hand.detection import presence_from_detection
    from orca_ui.hand.supervisor import load_config
    from orca_ui.settings import UiSettings
    from orca_core.hand_config import _resolve_config_path

    config = load_config(_resolve_config_path(None, model_name="orcahand-touch-right"))
    detection = HandDetection(
        model_name="orcahand-touch-right", side="right", has_tactile=True,
        has_encoders=False, motor_port="/dev/motor", sensing_port="/dev/oh",
        identity=OrcaBoardInfo(role="motor", side="right", serial="ser-0000"))
    presence = presence_from_detection(config, detection)
    built = []

    class FakeHand:
        def __init__(self, tactile):
            self.config = SimpleNamespace(port="/dev/motor")
            self.disconnected = False
            if tactile:
                self._tactile_client = SimpleNamespace(
                    _tactile_config=SimpleNamespace(num_active_sensors=0))

        def connect(self, interactive=False):
            return True, "ok"

        def is_connected(self):
            return True

        def disconnect(self):
            self.disconnected = True
            return True, "closed"

    def build(settings, config, feedback, tactile):
        hand = FakeHand(tactile)
        built.append(hand)
        return hand

    monkeypatch.setattr(sessions, "_build_hand", build)
    declared = sessions.declared_capabilities(config, True, motors_enabled=True)

    session = sessions._connect_with_motors(
        UiSettings(config_path=config.config_path, open_browser=False),
        config, declared, presence)

    assert session.tier == "motors" and not session.caps.tactile
    assert built[0].disconnected and session.hand is built[1]

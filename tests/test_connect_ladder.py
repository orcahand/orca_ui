"""Degradation-ladder unit tests with scripted fake hands (no hardware)."""

import pytest

from orca_core.hardware.sensing.serial_discovery import SensingPorts
from orca_core.hardware_hand_joint_feedback import JointFeedbackConnectError

import orca_ui.hand.sessions as sessions
from orca_ui.hand.detection import HardwarePresence
from orca_ui.hand.sessions import SessionConnectError, _connect_with_motors
from orca_ui.mock import materialize_mock_model
from orca_ui.settings import UiSettings


class FakeHand:
    """Scripted hand: behavior keyed by (feedback, tactile) tier."""

    def __init__(self, feedback, tactile, script):
        self.feedback = feedback
        self.tactile = tactile
        self._script = script  # tier -> "ok" | "raise" | "partial" | "fail"
        self._connected = False
        self._tactile_client = object() if tactile else None
        self._loop = object() if feedback else None

    def connect(self):
        behavior = self._script.get((self.feedback, self.tactile), "ok")
        if behavior == "raise":
            raise JointFeedbackConnectError("no encoder calibration")
        if behavior == "partial":  # motors up, sensor failed (touch semantics)
            self._connected = True
            self._tactile_client = None
            return False, "motor ok | sensor failed"
        if behavior == "fail":
            return False, "connection failed"
        self._connected = True
        return True, "ok"

    def is_connected(self):
        return self._connected


@pytest.fixture()
def env(monkeypatch):
    settings = UiSettings(config_path=materialize_mock_model(), mock=False,
                          open_browser=False)

    def install(script):
        def fake_build(_settings, _config, feedback, tactile):
            return FakeHand(feedback, tactile, script)

        def fake_caps(hand, declared):
            from orca_ui.hand.states import Capabilities
            feedback = hand.feedback and hand._loop is not None
            return Capabilities(
                motors=hand.is_connected(),
                tactile=hand._tactile_client is not None,
                encoders=feedback, feedback_loop=feedback, declared=declared,
            )

        monkeypatch.setattr(sessions, "_build_hand", fake_build)
        monkeypatch.setattr(sessions, "_caps_from_hand", fake_caps)

    presence = HardwarePresence(
        motor_port="/dev/motor",
        sensing=SensingPorts(tactile="/dev/oh", encoder="/dev/oh"),
    )
    declared = {"motors": True, "tactile": True, "encoders": True,
                "feedback_loop": True}
    return settings, declared, presence, install


def test_full_tier_connects_first_try(env):
    settings, declared, presence, install = env
    install({})
    session = _connect_with_motors(settings, None, declared, presence)
    assert session.tier == "full"
    assert session.caps.feedback_loop and session.caps.tactile


def test_feedback_failure_degrades_to_touch(env):
    settings, declared, presence, install = env
    install({(True, True): "raise", (True, False): "raise"})
    session = _connect_with_motors(settings, None, declared, presence)
    assert session.tier == "touch"
    assert session.caps.tactile and not session.caps.feedback_loop
    assert session.caps.degraded


def test_touch_partial_keeps_motor_bus(env):
    settings, declared, presence, install = env
    install({(True, True): "raise", (True, False): "raise",
             (False, True): "partial"})
    session = _connect_with_motors(settings, None, declared, presence)
    assert session.tier == "motors"
    assert session.caps.motors and not session.caps.tactile


def test_all_tiers_failing_raises_with_attempts(env):
    settings, declared, presence, install = env
    install({(True, True): "raise", (True, False): "raise",
             (False, True): "fail", (False, False): "fail"})
    with pytest.raises(SessionConnectError) as exc:
        _connect_with_motors(settings, None, declared, presence)
    assert len(exc.value.attempts) == 4


def test_missing_sensing_ports_narrow_the_ladder(env):
    settings, declared, presence, install = env
    install({})
    no_sensing = HardwarePresence(
        motor_port="/dev/motor", sensing=SensingPorts(tactile=None, encoder=None))
    session = _connect_with_motors(settings, None, declared, no_sensing)
    assert session.tier == "motors"
    assert session.caps.degraded


def test_motor_tier_failures_fall_back_to_sensors_only(env, monkeypatch):
    """A motor port that answers but won't connect (unpowered motors, broken
    motor stack) must not block sensor viewing."""
    settings, declared, presence, install = env
    install({(True, True): "raise", (True, False): "raise",
             (False, True): "fail", (False, False): "fail"})

    sentinel = object()
    monkeypatch.setattr(sessions, "probe_hardware", lambda config: presence)
    monkeypatch.setattr(sessions, "_connect_sensors_only",
                        lambda *args: sentinel)
    monkeypatch.setattr(sessions, "declared_capabilities",
                        lambda *args, **kwargs: declared)

    assert sessions.connect_session(settings, None) is sentinel


def test_no_motors_flag_skips_motor_tiers(env, monkeypatch):
    import dataclasses
    settings, declared, presence, install = env
    settings = dataclasses.replace(settings, motors_enabled=False)

    def explode(*args):
        raise AssertionError("motor tiers must not run with --no-motors")

    sentinel = object()
    monkeypatch.setattr(sessions, "probe_hardware", lambda config: presence)
    monkeypatch.setattr(sessions, "_connect_with_motors", explode)
    monkeypatch.setattr(sessions, "_connect_sensors_only",
                        lambda *args: sentinel)
    monkeypatch.setattr(sessions, "declared_capabilities",
                        lambda *args, **kwargs: declared)

    assert sessions.connect_session(settings, None) is sentinel

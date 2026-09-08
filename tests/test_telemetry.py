"""Telemetry sampler tests: what the ticks are allowed to put on the motor bus.

A group read holds the servo bus for the whole transaction, and the joint loop
writes over that same bus every 10 ms. A read taken while the hand is moving
therefore freezes it for a cycle or more. These pin when a read is allowed to
happen at all.
"""

from orca_ui.hand.telemetry import (
    MOTOR_TELEMETRY_MIN_INTERVAL_S,
    TelemetryService,
)


class _Caps:
    def __init__(self, feedback_loop=True):
        self.motors = True
        self.encoders = True
        self.tactile = False
        self.feedback_loop = feedback_loop


class _State:
    position = [0.0]
    velocity = [0.0]
    current = [5.0]


class _Config:
    motor_ids = [1]


class _Hand:
    def __init__(self):
        self.bus_reads: list[str] = []
        self.config = _Config()

    def get_motor_pos(self, as_dict=False):
        self.bus_reads.append("pos")
        return {}

    def get_motor_state(self):
        self.bus_reads.append("state")
        return _State()

    def get_motor_temp(self, as_dict=False):
        self.bus_reads.append("temp")
        return {1: 30.0}

    def get_motor_current(self, as_dict=False):
        self.bus_reads.append("current")
        return {1: 5.0}


class _Session:
    def __init__(self, feedback_loop=True):
        self.caps = _Caps(feedback_loop)
        self.hand = _Hand()

    def estimate_joints(self):
        return self.hand.get_motor_pos()

    def motor_snapshot(self):
        state = self.hand.get_motor_state()
        return {"index_mcp": 5.0}, dict(zip(self.hand.config.motor_ids,
                                            state.current))

    def loop_correction(self):
        return {"index_mcp": 0.1}

    def measured_joints(self):
        return {"index_mcp": 10.0}


class _Manager:
    def __init__(self, active=False):
        self._active = active

    def active(self):
        return self._active


class _Worker:
    def __init__(self, ramping=False):
        self._ramping = ramping

    def stats(self):
        return {"ramping": self._ramping}


class _Service:
    def __init__(self, session, ramping=False, op_active=False):
        self.session = session
        self.worker = _Worker(ramping)
        self.operation_manager = _Manager(op_active)

    def stats(self):
        return {}


class _Hub:
    def __init__(self):
        self.published: list[str] = []

    def publish(self, topic, payload):
        self.published.append(topic)


class _Settings:
    fast_hz = 60.0
    mid_hz = 10.0
    slow_hz = 1.0


def _build(ramping=False, op_active=False, feedback_loop=True):
    session = _Session(feedback_loop)
    service = _Service(session, ramping, op_active)
    telemetry = TelemetryService(service, _Hub(), _Settings())
    return telemetry, session


def test_no_bus_reads_while_a_target_ramp_is_in_flight():
    """Streamed motion (slider, replay, demo, teleop) must not be interrupted."""
    telemetry, session = _build(ramping=True)
    for _ in range(5):
        telemetry._slow_tick()
    assert session.hand.bus_reads == []


def test_no_bus_reads_while_an_operation_runs():
    """Ops that drive the hand themselves (go-neutral, pose apply) also count
    as motion, even though they never ramp a target stream."""
    telemetry, session = _build(op_active=True)
    for _ in range(5):
        telemetry._slow_tick()
    assert session.hand.bus_reads == []


def test_a_hand_without_a_loop_rate_limits_its_telemetry_reads():
    """Nothing contends for the bus, but each read still blocks commands for
    its round trip and temperature moves over minutes."""
    telemetry, session = _build(feedback_loop=False)
    for _ in range(5):
        telemetry._slow_tick()
    assert session.hand.bus_reads == ["temp", "current"]


def test_the_loopless_read_returns_once_the_interval_has_passed():
    telemetry, session = _build(feedback_loop=False)
    telemetry._slow_tick()
    session.hand.bus_reads.clear()

    telemetry._last_motor_telemetry -= MOTOR_TELEMETRY_MIN_INTERVAL_S
    telemetry._slow_tick()

    assert session.hand.bus_reads == ["temp", "current"]


# ----- measured-stream fallback for unhealthy encoders ---------------------------


from orca_ui.hand.telemetry import ENCODER_RESTORE_WINDOWS  # noqa: E402


def _health(verdict, joint="index_mcp"):
    return {"encoders": {"joints": {joint: {"verdict": verdict,
                                            "reason": "test"}}}}


def test_encoder_suppression_fast_to_condemn_slow_to_forgive():
    telemetry, _ = _build()
    telemetry._update_encoder_suppression(_health("parity"))
    assert "index_mcp" in telemetry._enc_suppressed

    # Clean windows one short of the threshold: still suppressed (flapping
    # must not leak noise bursts).
    for _ in range(ENCODER_RESTORE_WINDOWS - 1):
        telemetry._update_encoder_suppression(_health("live"))
        assert "index_mcp" in telemetry._enc_suppressed

    # A relapse resets the streak entirely.
    telemetry._update_encoder_suppression(_health("parity"))
    for _ in range(ENCODER_RESTORE_WINDOWS - 1):
        telemetry._update_encoder_suppression(_health("live"))
        assert "index_mcp" in telemetry._enc_suppressed

    telemetry._update_encoder_suppression(_health("live"))
    assert telemetry._enc_suppressed == {}

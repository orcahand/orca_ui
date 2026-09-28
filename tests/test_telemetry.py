"""Telemetry sampler tests: what the ticks are allowed to put on the motor bus.

A bulk read holds the servo bus for a round trip per motor (~15 ms on a
17-motor hand), and the joint loop writes over that same bus every 10 ms. A
read taken while the hand is moving therefore freezes it for a cycle and a
half. These pin when a read is allowed to happen at all.
"""

import pytest

from orca_ui.hand.telemetry import MAX_TELEMETRY_STALENESS_S, TelemetryService


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


def test_idle_hand_reads_one_register_block_per_tick():
    """Still hand: reads resume, but only one per tick so two never queue up
    back to back on the bus."""
    telemetry, session = _build()
    for _ in range(4):
        telemetry._slow_tick()
    assert session.hand.bus_reads == ["state", "temp", "state", "temp"]


def test_position_and_current_cost_one_read_not_two():
    """They share a register block. Asking for them separately would pay two
    full round trips to every motor for one transaction's data."""
    telemetry, session = _build()
    telemetry._slow_tick()
    assert session.hand.bus_reads == ["state"]
    assert "pos" not in session.hand.bus_reads
    assert "current" not in session.hand.bus_reads


def test_a_long_motion_still_gets_telemetry_eventually():
    """Reads yield to motion, but not forever — an overheating motor during a
    long replay must still surface."""
    telemetry, session = _build(ramping=True)
    telemetry._last_bus_read -= MAX_TELEMETRY_STALENESS_S + 1.0
    telemetry._slow_tick()
    assert session.hand.bus_reads == ["state"]


def test_hand_without_a_loop_is_unrestricted():
    """No loop means no writes to stall, so the livelier cadence stands."""
    telemetry, session = _build(ramping=True, feedback_loop=False)
    telemetry._slow_tick()
    assert session.hand.bus_reads == ["temp", "current"]


@pytest.mark.parametrize("ramping,op_active", [(True, False), (False, True)])
def test_driven_detection(ramping, op_active):
    telemetry, _ = _build(ramping=ramping, op_active=op_active)
    assert telemetry._hand_is_driven()

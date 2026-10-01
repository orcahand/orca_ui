"""Telemetry sampler tests: what the ticks are allowed to put on the motor bus.

A group read holds the servo bus for the whole transaction, and the joint loop
writes over that same bus every 10 ms. A read taken while the hand is moving
therefore freezes it for a cycle or more. These pin when a read is allowed to
happen at all.
"""

from types import SimpleNamespace

from orca_ui.hand.telemetry import (
    MAX_TELEMETRY_STALENESS_S,
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
    def __init__(self, ramping=False, applied=None):
        self._ramping = ramping
        self._applied = dict(applied or {})

    def stats(self):
        return {"ramping": self._ramping}

    def applied_targets(self):
        return dict(self._applied)


class _Service:
    def __init__(self, session, ramping=False, op_active=False,
                 torque=False, applied=None, pose_source="estimate"):
        self.session = session
        self.worker = _Worker(ramping, applied)
        self.operation_manager = _Manager(op_active)
        self.supervisor = SimpleNamespace(
            status=lambda: SimpleNamespace(torque_enabled=torque))
        self._direct_motor_mode = False
        self._pose_source = pose_source

    def effective_pose_source(self):
        return self._pose_source

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


def _build(ramping=False, op_active=False, feedback_loop=True,
           torque=False, applied=None, pose_source="estimate"):
    session = _Session(feedback_loop)
    service = _Service(session, ramping, op_active, torque, applied, pose_source)
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


def test_a_long_motion_still_gets_telemetry_eventually():
    """Reads yield to motion, but not forever — an overheating motor during a
    long replay must still surface."""
    telemetry, session = _build(ramping=True)
    telemetry._last_bus_read -= MAX_TELEMETRY_STALENESS_S + 1.0
    telemetry._slow_tick()
    assert session.hand.bus_reads == ["temp"]
    # The forced read resets the clock: the next tick defers again.
    telemetry._slow_tick()
    assert session.hand.bus_reads == ["temp"]


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


# ----- pose source gates the estimate read ----------------------------------


class _PoseSourceService(_Service):
    def __init__(self, session, source='estimate'):
        super().__init__(session)
        self._pose_source_value = source

    def effective_pose_source(self):
        return self._pose_source_value


def _build_with_source(source, feedback_loop=False):
    session = _Session(feedback_loop)
    service = _PoseSourceService(session, source)
    telemetry = TelemetryService(service, _Hub(), _Settings())
    return telemetry, session


def test_estimate_is_read_while_the_model_follows_it():
    telemetry, session = _build_with_source('estimate')
    telemetry._mid_tick()
    assert session.hand.bus_reads == ['pos']


def test_no_estimate_read_once_the_model_follows_commands():
    """Half-duplex bus: a read while streaming targets blocks the commands it
    is competing with, and the model is not showing the estimate anyway."""
    telemetry, session = _build_with_source('target')
    for _ in range(5):
        telemetry._mid_tick()
    assert session.hand.bus_reads == []


# ----- command adherence ------------------------------------------------------


def test_tracking_compares_what_was_written_against_what_the_hand_did():
    """Stall detection is only alive if the worker's applied targets reach the
    monitor. The call is wrapped in a try/except, so a missing accessor leaves
    tracking permanently null and the TRACK column permanently blank — which is
    indistinguishable from a healthy hand."""
    # Commanded and measured agree: following, no stall.
    telemetry, _ = _build(torque=True, applied={"index_mcp": 10.0})
    telemetry._mid_tick()
    tracking = telemetry._tracking.snapshot()
    assert tracking["index_mcp"]["following"] is True

    # Commanded far from where the hand actually is: the gap is recorded. It
    # only becomes a stall once it outlasts TRACKING_GRACE_S, which is the
    # monitor's own business — what matters here is that the gap arrives.
    telemetry, _ = _build(torque=True, applied={"index_mcp": 80.0})
    telemetry._mid_tick()
    assert telemetry._tracking.snapshot()["index_mcp"]["deviation_deg"] == 70.0


def test_tracking_still_runs_when_the_model_follows_targets():
    """In the default pose source the mid tick stops polling the estimate
    once torque is on, which is the only time a stall can happen; tracking
    then takes one motor read a second from the slow tick instead."""
    telemetry, session = _build(feedback_loop=False, torque=True,
                                applied={"index_mcp": 30.0}, pose_source="target")
    session.caps.encoders = False
    for _ in range(3):
        telemetry._mid_tick()
    assert "pos" not in session.hand.bus_reads
    telemetry._slow_tick()
    assert "state" in session.hand.bus_reads
    assert telemetry._tracking._joints["index_mcp"].deviation == 25.0
    # The next mid tick must not wipe what the slow tick measured.
    telemetry._mid_tick()
    assert telemetry._tracking._joints["index_mcp"].deviation == 25.0


def test_a_dead_stream_is_not_suppressed_joint_by_joint():
    telemetry, _ = _build()
    telemetry._update_encoder_suppression(_health("no frames"))
    assert telemetry._enc_suppressed == {}


class TestSpotlightPayload:
    """One silent motor must not take the whole panel down.

    The stream envelope is built with allow_nan=False and the broadcaster
    marks a topic that failed to serialise as sent, so it never retries: a
    single NaN would stop the panel permanently rather than leave a gap.
    """

    def _service(self, currents):
        import types
        from orca_ui.hand import telemetry as tm

        published = []

        class _Hub:
            def publish(self, topic, payload):
                published.append((topic, payload))

        class _Hand:
            config = types.SimpleNamespace(motor_ids=[1, 2])

            def get_motor_state(self):
                return types.SimpleNamespace(
                    position=[0.5, float("nan")],
                    current=[currents[1], currents[2]])

            def get_motor_temp(self, as_dict=True):
                return {1: 30.0, 2: float("nan")}

        session = types.SimpleNamespace(
            hand=_Hand(), caps=types.SimpleNamespace(motors=True),
            # An uncalibrated hand has no motor-to-joint mapping, which is
            # the case this panel has to stay usable in.
            _estimate_allowed=lambda: False)
        service = tm.TelemetryService(
            types.SimpleNamespace(session=session), _Hub(),
            types.SimpleNamespace(fast_hz=60, mid_hz=10, slow_hz=1))
        service.set_spotlight(enabled=True, sample_hz=200, publish_hz=1000,
                              average_samples=4)
        return service, published

    def test_a_silent_motor_leaves_a_gap_rather_than_a_nan(self):
        service, published = self._service({1: 10.0, 2: float("nan")})
        service._spotlight_tick()

        payload = next(p for topic, p in published if topic == "spotlight")
        assert payload["positions"] == {1: 0.5}
        assert payload["currents"] == {1: 10.0}
        assert 2 not in payload["temps"]

    def test_the_payload_survives_json_with_nan_refused(self):
        """Exactly how the envelope encodes it."""
        import json

        service, published = self._service({1: 10.0, 2: float("nan")})
        service._spotlight_tick()
        payload = next(p for topic, p in published if topic == "spotlight")

        json.dumps(payload, allow_nan=False)  # must not raise

    def test_an_all_nan_read_still_publishes(self):
        """Empty is a legitimate answer; refusing to publish would leave the
        panel showing a stale reading with no sign it had gone."""
        service, published = self._service({1: float("nan"), 2: float("nan")})
        service._spotlight_tick()

        payload = next(p for topic, p in published if topic == "spotlight")
        assert payload["currents"] == {}
        assert "achieved_hz" in payload

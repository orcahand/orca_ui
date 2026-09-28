"""CommandWorker tests: setpoint interpolation between commanded frames.

The worker exists to turn a low-rate target stream into one setpoint per
joint-loop cycle. These drive it synchronously (no thread) so the ramp is
checked at exact times rather than raced against a real clock.
"""

import pytest

from orca_ui.hand.commands import DEFAULT_COMMAND_PERIOD_S, CommandWorker


class _Caps:
    motors = True


class _Hand:
    def __init__(self):
        self.writes: list[dict] = []

    def set_joint_positions(self, angles):
        self.writes.append(dict(angles))


class _Session:
    def __init__(self):
        self.caps = _Caps()
        self.hand = _Hand()


class _Clock:
    """Manual clock: the ramp is time-driven, so tests step it explicitly
    rather than racing the real one."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture()
def clock():
    return _Clock()


@pytest.fixture()
def worker(clock):
    session = _Session()
    return CommandWorker(get_session=lambda: session, clock=clock)


def _drain(worker, clock, ticks, step=0.01):
    """Pump `ticks` feed cycles, returning what got written."""
    written = []
    for _ in range(ticks):
        pose = worker._next_write(clock.now)
        if pose is not None:
            written.append(pose)
        clock.advance(step)
    return written


def test_first_command_snaps_then_holds(worker, clock):
    """Nothing is known about where the joint is, so the first command is
    applied as given — and is written exactly once, not resent forever."""
    worker.submit_targets({"index_mcp": 10.0})
    assert _drain(worker, clock, 5) == [{"index_mcp": 10.0}]


def test_stream_is_interpolated_not_stepped(worker, clock):
    """A 25 Hz stream cruising 2.4 deg per frame must reach the loop as a ramp.

    This is the whole point of the worker: before interpolation the loop saw
    one 2.4 deg step every 40 ms and the joint ratcheted at the frame rate.
    """
    worker.submit_targets({"index_mcp": 0.0})
    _drain(worker, clock, 1)

    # Frames at 25 Hz, so the period estimate settles on the real spacing.
    for frame in (2.4, 4.8):
        worker.submit_targets({"index_mcp": frame})
        _drain(worker, clock, 4)

    worker.submit_targets({"index_mcp": 7.2})
    values = [w["index_mcp"] for w in _drain(worker, clock, 10)]

    assert len(values) >= 3, values
    assert values == sorted(values)
    # Every sub-step is smaller than the 2.4 deg the source commanded, and the
    # frame is crossed by intermediate setpoints rather than in one jump.
    assert all(b - a < 2.4 for a, b in zip(values, values[1:]))
    assert values[0] == pytest.approx(4.8)
    assert values[-1] == pytest.approx(7.2)
    assert any(4.8 < v < 7.2 for v in values), values


def test_slow_source_ramps_across_the_whole_gap(worker, clock):
    """A 10 Hz source must be interpolated over its full 100 ms frame.

    The period is seeded from the first observed gap rather than smoothed up
    from the default: creeping up would spend the opening frames ramping over
    20 ms and then sitting idle for 80 ms, which is the staircase again.
    """
    worker.reset({"index_mcp": 0.0})
    for frame in (6.0, 12.0):
        worker.submit_targets({"index_mcp": frame})
        _drain(worker, clock, 10)          # 100 ms of feed at 100 Hz

    worker.submit_targets({"index_mcp": 18.0})
    # The ramp spans RAMP_SLACK x the 100 ms gap, so it is still in flight when
    # the next frame would have landed and converges at the 150 ms mark.
    values = [w["index_mcp"] for w in _drain(worker, clock, 20)]

    assert values == sorted(values)
    # Sub-steps across the whole span, not one 6 deg jump and 90 ms of idle.
    assert len(values) == 16
    assert max(b - a for a, b in zip(values, values[1:])) < 1.0
    assert values[-1] == pytest.approx(18.0)


def test_ramp_lands_exactly_on_the_commanded_value(worker, clock):
    """Interpolation must not leave steady-state error behind."""
    worker.submit_targets({"index_mcp": 0.0})
    _drain(worker, clock, 1)
    worker.submit_targets({"index_mcp": 30.0})
    assert _drain(worker, clock, 40)[-1] == {"index_mcp": 30.0}


def test_a_late_frame_does_not_strand_the_ramp(worker, clock):
    """No real source is perfectly paced, and the late frames are what hurt.

    A ramp sized to exactly one gap arrives while the next frame is still in
    flight; an arrived ramp stops emitting setpoints, so the joint holds for a
    feed slot and the motion ripples at the source's frame rate. The ramp
    spans past the measured gap so a late frame still finds it moving.
    """
    worker.reset({"index_mcp": 0.0})
    for frame in (1.0, 2.0):           # seed the period at a 20 ms cadence
        worker.submit_targets({"index_mcp": frame})
        _drain(worker, clock, 2)

    # This frame runs 50% late — 30 ms after the last, against a 20 ms estimate.
    worker.submit_targets({"index_mcp": 3.0})
    written = _drain(worker, clock, 3)

    assert len(written) == 3, written
    assert [w["index_mcp"] for w in written] == sorted(w["index_mcp"] for w in written)
    # Still short of the target: the ramp is live when the next frame lands,
    # rather than parked on it waiting.
    assert written[-1]["index_mcp"] < 3.0


def test_settled_joint_is_not_rewritten_by_a_later_command(worker, clock):
    """A joint that has arrived stops being commanded. Otherwise a slider
    touch on one finger would re-drive every joint the worker ever saw — to
    targets that may predate a torque toggle."""
    worker.submit_targets({"index_mcp": 10.0})
    _drain(worker, clock, 40)

    worker.submit_targets({"thumb_mcp": 5.0})
    written = _drain(worker, clock, 40)
    assert written
    assert all("index_mcp" not in pose for pose in written)


def test_reset_seeds_the_next_ramp(worker, clock):
    """After a torque toggle the ramp restarts from the real pose, so the
    next command glides out of it instead of snapping."""
    worker.reset({"index_mcp": 20.0})
    worker.submit_targets({"index_mcp": 40.0})
    first = worker._next_write(clock.now)
    assert first is not None
    assert 20.0 <= first["index_mcp"] < 40.0

    assert _drain(worker, clock, 40)[-1] == {"index_mcp": 40.0}


def test_reset_drops_an_in_flight_ramp(worker, clock):
    worker.reset({"index_mcp": 0.0})
    worker.submit_targets({"index_mcp": 50.0})
    worker._next_write(clock.now)
    worker.reset()
    clock.advance(DEFAULT_COMMAND_PERIOD_S)
    assert worker._next_write(clock.now) is None


def test_a_late_command_never_drives_the_joint_backwards(worker, clock):
    """The feed samples the clock before taking the lock, so a command can
    land with a timestamp ahead of `now`. That must hold, not extrapolate."""
    worker.reset({"index_mcp": 0.0})
    stale = clock.now
    clock.advance(0.05)
    worker.submit_targets({"index_mcp": 10.0})
    assert worker._next_write(stale) == {"index_mcp": 0.0}

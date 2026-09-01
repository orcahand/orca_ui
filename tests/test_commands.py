"""CommandWorker tests: setpoint interpolation between commanded frames.

The worker exists to turn a low-rate target stream into one setpoint per
joint-loop cycle. These drive it synchronously (no thread) so the ramp is
checked at exact times rather than raced against a real clock.
"""

import pytest

from orca_ui.hand.commands import CommandWorker


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


def test_a_late_command_never_drives_the_joint_backwards(worker, clock):
    """The feed samples the clock before taking the lock, so a command can
    land with a timestamp ahead of `now`. That must hold, not extrapolate."""
    worker.reset({"index_mcp": 0.0})
    stale = clock.now
    clock.advance(0.05)
    worker.submit_targets({"index_mcp": 10.0})
    assert worker._next_write(stale) == {"index_mcp": 0.0}

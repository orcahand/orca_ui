"""Serialized motor command execution.

Target streams are coalesced latest-wins and fed to the hand at ``FEED_HZ``,
linearly interpolated between arrivals. Sources command at whatever rate suits
them — a slider at pointer rate, replay at its frame rate — and the joint loop
still gets a fresh setpoint every cycle instead of a staircase to chase.

Without that the steps are large and slow enough to feel: replay cruising at
``WAYPOINT_SPEED_DEG_S`` (60 deg/s) at 25 Hz hands the 100 Hz PI a 2.4 deg step
four cycles apart, and since the controller has no derivative term each edge
becomes an instant ``Kp x step`` jump in the motor target — the joint ratchets
at the command rate. ``apply_pose`` already avoids this by passing orca_core's
``num_steps``/``step_size``; this does the same for streamed targets, whose
frame spacing isn't known up front.

Long-running exclusive ops (go-to-neutral, pose apply) run on the same thread
so they never interleave with target writes, and reset the ramp afterwards
because they move the hand out from under it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# One setpoint per joint-loop cycle; must track orca_core's DEFAULT_LOOP_HZ,
# since feeding slower leaves the loop re-using setpoints in between.
FEED_HZ = 200.0

# Command spacing is measured rather than assumed, so a 50 Hz replay and a
# slider at pointer rate each ramp over their own inter-command gap. Clamped
# so a stalled source can't stretch one ramp into a crawl, and a burst can't
# collapse it back into a step.
DEFAULT_COMMAND_PERIOD_S = 1.0 / 50.0
MIN_COMMAND_PERIOD_S = 1.0 / 200.0
MAX_COMMAND_PERIOD_S = 0.2
PERIOD_SMOOTHING = 0.3

# The ramp outlasts one measured gap, so a late frame still finds it in flight
# instead of parked on its target. Costs this many frames of lag instead of one.
RAMP_SLACK = 1.5


class CommandWorker(threading.Thread):
    def __init__(
        self,
        get_session: Callable[[], object | None],
        on_error: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        super().__init__(name="CommandWorker", daemon=True)
        self._get_session = get_session
        self._on_error = on_error or (lambda message: None)
        self._clock = clock
        self._lock = threading.Lock()
        self._ops: deque[Callable[[], None]] = deque()
        self._wake = threading.Event()
        self._stop_event = threading.Event()

        # Active ramp: per-joint start and destination, plus when the
        # destination was commanded and how far apart commands are arriving.
        self._from: dict[str, float] = {}
        self._to: dict[str, float] = {}
        self._commanded_at = 0.0
        self._period = DEFAULT_COMMAND_PERIOD_S
        self._period_seeded = False
        # Last value actually written per joint — where the next ramp for that
        # joint starts. Only joints under an active ramp are ever written, so
        # this never resurrects a stale target for a joint nobody commanded.
        self._applied: dict[str, float] = {}
        self._writes = 0

    def stats(self) -> dict:
        """Cumulative counters, diffed by the caller like the loop's — the feed
        rate during motion is the observable that says interpolation is live."""
        with self._lock:
            return {
                "writes": self._writes,
                "feed_hz": FEED_HZ,
                "command_period_ms": round(self._period * 1000, 2),
                "ramping": bool(self._to),
            }

    def submit_targets(self, angles: dict[str, float]) -> None:
        now = self._clock()
        with self._lock:
            if self._commanded_at:
                gap = now - self._commanded_at
                if MIN_COMMAND_PERIOD_S <= gap <= MAX_COMMAND_PERIOD_S:
                    if self._period_seeded:
                        self._period += PERIOD_SMOOTHING * (gap - self._period)
                    else:
                        # Take the first gap whole. Smoothing up from the
                        # default would spend the first several frames of a
                        # slow source ramping early and then idling — exactly
                        # the staircase this exists to remove.
                        self._period = gap
                        self._period_seeded = True
            # Restart each named joint's ramp from wherever it actually got to,
            # so a stream stays continuous instead of re-stepping every frame.
            live = self._pose_at(now)
            for joint, value in angles.items():
                value = float(value)
                self._from[joint] = live.get(
                    joint, self._applied.get(joint, value))
                self._to[joint] = value
            self._commanded_at = now
        self._wake.set()

    def submit_op(self, op: Callable[[], None]) -> None:
        """Queue an exclusive operation (e.g. go-to-neutral)."""
        with self._lock:
            self._ops.append(op)
        self._wake.set()

    def reset(self, pose: dict[str, float] | None = None) -> None:
        """Drop the ramp and re-seed where joints are believed to be.

        Called when the hand moves out from under the interpolator — a torque
        toggle, an e-stop, a completed op — so the next command starts from the
        real pose rather than ramping out of a stale one.
        """
        with self._lock:
            self._from.clear()
            self._to.clear()
            self._applied = {j: float(v) for j, v in (pose or {}).items()}
            self._commanded_at = 0.0
            self._period = DEFAULT_COMMAND_PERIOD_S
            self._period_seeded = False

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake.set()
        self.join(timeout=2.0)

    # ----- ramp ---------------------------------------------------------------

    def _pose_at(self, now: float) -> dict[str, float]:
        """Interpolated pose for the joints under an active ramp. Caller holds
        the lock."""
        if not self._to:
            return {}
        span = self._period * RAMP_SLACK
        if span <= 0.0:
            return dict(self._to)
        # Clamped both ways: the caller samples the clock before taking the
        # lock, so a command landing in that window would otherwise give a
        # negative alpha and extrapolate the joint backwards.
        alpha = min(1.0, max(0.0, (now - self._commanded_at) / span))
        if alpha >= 1.0:
            return dict(self._to)
        return {
            joint: start + (self._to[joint] - start) * alpha
            for joint, start in self._from.items()
        }

    def _next_write(self, now: float) -> Optional[dict[str, float]]:
        """Next pose to write, or None when the ramp has nothing left to do."""
        with self._lock:
            if not self._to:
                return None
            pose = self._pose_at(now)
            if pose == self._to:
                # Arrived: emit the commanded values exactly once, then stop
                # tracking these joints so a later command for a different
                # joint never rewrites this one's target.
                self._from.clear()
                self._to.clear()
            self._applied.update(pose)
            return pose

    # ----- thread -------------------------------------------------------------

    def run(self) -> None:
        period = 1.0 / FEED_HZ
        next_write = self._clock()
        while not self._stop_event.is_set():
            op = self._take_op()
            if op is not None:
                self._run_op(op)
                next_write = self._clock()
                continue

            now = self._clock()
            if now < next_write:
                # Pace off a deadline rather than a per-iteration timeout, so a
                # submit landing mid-interval wakes us for an op without also
                # buying itself an extra write.
                self._wake.wait(timeout=next_write - now)
                self._wake.clear()
                continue

            pose = self._next_write(now)
            if pose is None:
                # Sleep until something is submitted, leaving the deadline
                # alone so a ramp ending between frames resumes on its grid.
                self._wake.wait()
                self._wake.clear()
                continue

            self._write(pose)
            # Advance the deadline on its own grid, not from when this write
            # landed: wake-up overshoot is a few ms every cycle and would
            # otherwise accumulate into a visibly slower feed. Clamped to now
            # so a long stall can't produce a burst of catch-up writes.
            next_write = max(next_write + period, now)

    def _take_op(self) -> Optional[Callable[[], None]]:
        with self._lock:
            return self._ops.popleft() if self._ops else None

    def _run_op(self, op: Callable[[], None]) -> None:
        try:
            op()
        except Exception as e:
            logger.exception("command op failed")
            self._on_error(f"command failed: {e}")
        finally:
            # The op drove the hand itself; whatever the ramp was heading for
            # is stale now.
            self.reset()

    def _write(self, pose: dict[str, float]) -> None:
        session = self._get_session()
        if session is None or not session.caps.motors:
            return
        try:
            session.hand.set_joint_positions(pose)
            with self._lock:
                self._writes += 1
        except Exception as e:
            logger.exception("set_joint_positions failed")
            self._on_error(f"set_joint_positions failed: {e}")

"""Trajectory playback: the shared engine behind replay and demo.

The player owns frame pacing on the op thread and submits the latest frame
through ``service.set_targets(source=OPERATION)`` — full validation, torque
gate, and the ``joints.target`` echo apply. The command worker re-samples that
stream onto the joint-loop rate, so the frame rate here sets how faithfully the
commanded path reaches the loop.
"""

from __future__ import annotations

import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource
from orca_ui.library import CONTINUOUS, WAYPOINTS, LibraryError

SPEEDS = (0.5, 1.0, 2.0)
WAYPOINT_SPEED_DEG_S = 60.0   # cruise speed for synthesized waypoint segments
MIN_SEGMENT_S = 0.3           # floor so near-identical waypoints still glide
# Half the worker's feed rate — upsampling to the loop rate is its job, not
# this one's, and submitting faster only adds echo traffic and lock churn.
WAYPOINT_RATE_HZ = 100.0
LEAD_IN_MIN_DEG = 2.0         # skip the approach glide when already at start
PROGRESS_EVERY_S = 0.2
MAX_LOOP_CYCLES = 1000


def _require_playable(service) -> None:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("playback needs motors", status_code=409)
    if not service.supervisor.status().torque_enabled:
        raise ServiceError("torque is disabled — enable it first",
                           status_code=409)


def _segment_frames(start: list, end: list,
                    rate_hz: float) -> list[list[float]]:
    """Frames gliding from ``start`` to ``end`` at the cruise speed.

    Segment duration is proportional to the largest joint travel, so short
    adjustments and long sweeps move at the same angular speed. ``None``
    entries (unknown start pose or unrecorded joint) pass the end value
    through untouched — ``play_frames`` drops ``None`` before commanding.
    """
    deltas = [abs(b - a) for a, b in zip(start, end)
              if a is not None and b is not None]
    segment_s = max(max(deltas, default=0.0) / WAYPOINT_SPEED_DEG_S,
                    MIN_SEGMENT_S)
    steps = max(int(segment_s * rate_hz), 1)
    frames: list[list[float]] = []
    for step in range(steps):
        alpha = (step + 1) / steps
        frames.append([
            b if a is None or b is None else a + (b - a) * alpha
            for a, b in zip(start, end)
        ])
    return frames


def _interpolate(waypoints: list[list[float]],
                 rate_hz: float = WAYPOINT_RATE_HZ) -> tuple[list[list[float]], float]:
    """Expand sparse waypoints into linearly interpolated frames."""
    frames: list[list[float]] = []
    for start, end in zip(waypoints, waypoints[1:]):
        frames.extend(_segment_frames(start, end, rate_hz))
    return (frames or list(waypoints)), rate_hz


def _lead_in(service, joint_ids: list[str],
             first_row: list, rate_hz: float) -> list[list[float]]:
    """Approach glide from the measured pose to the first frame.

    Without it, the first command of playback jumps the hand from wherever
    it currently is at full motor speed. Empty when the pose is unknown or
    already within LEAD_IN_MIN_DEG of the start.
    """
    session = service.session
    measured = (session.measured_joints() or {}) if session else {}
    start = [measured.get(j) for j in joint_ids]
    deltas = [abs(b - a) for a, b in zip(start, first_row)
              if a is not None and b is not None]
    if max(deltas, default=0.0) < LEAD_IN_MIN_DEG:
        return []
    return _segment_frames(start, first_row, rate_hz)


def _stream(ctx: OpContext, joint_ids: list[str], frames: list[list[float]],
            dt: float, progress=None) -> None:
    """Command frames at a fixed cadence, honoring pause/stop."""
    total = len(frames)
    next_t = time.monotonic()
    last_progress = 0.0
    for index, row in enumerate(frames):
        ctx.check_stop()
        ctx.pause_point()
        angles = {j: float(v) for j, v in zip(joint_ids, row)
                  if v is not None}
        ctx.service.set_targets(angles, source=ControlSource.OPERATION)
        if progress is not None:
            now = time.monotonic()
            if now - last_progress >= PROGRESS_EVERY_S or index == total - 1:
                progress((index + 1) / total)
                last_progress = now
        next_t += dt
        delay = next_t - time.monotonic()
        if delay > 0:
            ctx.sleep(delay)


def play_frames(ctx: OpContext, *, name: str, joint_ids: list[str],
                frames: list[list[float]], rate_hz: float,
                speed: float, loop: bool) -> dict:
    """Paced playback with pause/stop; returns {frames, cycles}."""
    total = len(frames)
    if not total:
        return {"frames": 0, "cycles": 0, "duration_s": 0.0}
    duration_s = total / (rate_hz * speed)
    dt = 1.0 / (rate_hz * speed)
    cycles = 0

    # Approach glide runs once, at cruise pacing regardless of the
    # playback speed multiplier — it is not part of the recording.
    approach = _lead_in(ctx.service, joint_ids, frames[0], rate_hz)
    if approach:
        ctx.set_phase("approach", detail=f"{name} · moving to start")
        _stream(ctx, joint_ids, approach, 1.0 / rate_hz)

    ctx.set_phase("playing", progress=0.0,
                  detail=f"{name} · {duration_s:.1f}s @ ×{speed:g}")
    ctx.log(f"playing {name}: {total} frames, {duration_s:.1f}s at ×{speed:g}"
            f"{' (loop)' if loop else ''}")

    while True:
        _stream(ctx, joint_ids, frames, dt, progress=ctx.set_progress)
        cycles += 1
        if loop and cycles >= MAX_LOOP_CYCLES:
            ctx.log(f"loop backstop reached ({MAX_LOOP_CYCLES} cycles) — "
                    "stopping playback")
        if not loop or cycles >= MAX_LOOP_CYCLES:
            return {"frames": total, "cycles": cycles,
                    "duration_s": duration_s}
        ctx.set_detail(f"{name} · cycle {cycles + 1}")


class ReplayOperation(Operation):
    kind = "replay"
    control_source = ControlSource.OPERATION

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        _require_playable(service)
        name = params.get("name")
        try:
            data = service.library.load_trajectory(str(name or ""))
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)

        meta = data.get("metadata") or {}
        config = service.supervisor.config
        recorded_ids = meta.get("joint_ids")
        if recorded_ids is not None and list(recorded_ids) != list(config.joint_ids):
            raise ServiceError(
                "replay joint order does not match the connected hand config")
        if meta.get("hand_type") not in (None, config.type):
            raise ServiceError(
                f"recorded for hand_type={meta.get('hand_type')}, "
                f"connected is {config.type}")
        if meta.get("type") not in (CONTINUOUS, WAYPOINTS):
            raise ServiceError(f"unsupported trajectory type: {meta.get('type')!r}")
        if meta.get("type") == CONTINUOUS and not meta.get("sampling_frequency_hz"):
            raise ServiceError("continuous recording is missing sampling_frequency_hz")

        speed = float(params.get("speed", 1.0))
        if speed not in SPEEDS:
            raise ServiceError(f"speed must be one of {sorted(SPEEDS)}")
        frames = data.get("angles") or data.get("waypoints") or []
        if not frames:
            raise ServiceError("trajectory contains no frames")
        return {
            "name": str(name),
            "speed": speed,
            "loop": bool(params.get("loop", False)),
            "type": meta.get("type"),
        }

    def run(self, ctx: OpContext) -> dict:
        data = ctx.service.library.load_trajectory(self.params["name"])
        meta = data.get("metadata") or {}
        joint_ids = list(meta.get("joint_ids")
                         or ctx.service.supervisor.config.joint_ids)
        if meta.get("type") == CONTINUOUS:
            frames = data.get("angles") or []
            rate_hz = float(meta["sampling_frequency_hz"])
        else:
            waypoints = data.get("waypoints") or []
            # Close the cycle when looping so the wrap-around glides back
            # to the first waypoint instead of jumping at motor speed.
            if self.params["loop"] and len(waypoints) > 1:
                waypoints = waypoints + [list(waypoints[0])]
            frames, rate_hz = _interpolate(waypoints)
        return play_frames(
            ctx, name=self.params["name"], joint_ids=joint_ids,
            frames=frames, rate_hz=rate_hz,
            speed=self.params["speed"], loop=self.params["loop"],
        )


class DemoOperation(Operation):
    kind = "demo"
    control_source = ControlSource.OPERATION

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        _require_playable(service)
        name = str(params.get("name") or "")
        if name not in service.list_demos():
            raise ServiceError(
                f"unknown demo: {name!r} "
                f"(available: {sorted(service.list_demos())})",
                status_code=404)
        loop = bool(params.get("loop", False))
        cycles = int(params.get("cycles", 1))
        if not loop and not 1 <= cycles <= 10:
            raise ServiceError("cycles must be between 1 and 10")
        return {"name": name, "cycles": 1 if loop else cycles, "loop": loop}

    def run(self, ctx: OpContext) -> dict:
        service = ctx.service
        session = service.session
        if session is None:
            from orca_ui.hand.service import ServiceError
            raise ServiceError("hand not connected", status_code=503)
        keyframes = service.list_demos()[self.params["name"]]
        joint_ids = list(service.supervisor.config.joint_ids)
        # Looping playback wraps a single cycle (play_frames repeats it);
        # finite playback bakes the cycles into the frame list so the
        # progress bar spans the whole run.
        repeats = 1 if self.params["loop"] else self.params["cycles"]
        waypoints = []
        for fractions in keyframes * repeats:
            pose = hand_ops.pose_from_fractions(session.hand, fractions)
            waypoints.append([pose.get(j) for j in joint_ids])
        # When looping, close the cycle so the wrap-around glides back to
        # the first keyframe instead of jumping.
        if self.params["loop"] and waypoints:
            waypoints.append(list(waypoints[0]))
        frames, rate_hz = _interpolate(waypoints)
        return play_frames(
            ctx, name=self.params["name"], joint_ids=joint_ids,
            frames=frames, rate_hz=rate_hz, speed=1.0,
            loop=self.params["loop"],
        )

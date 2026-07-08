"""Trajectory playback: the shared engine behind replay and demo.

The player owns frame pacing on the op thread and submits the latest frame
through ``service.set_targets(source=OPERATION)`` — full validation, torque
gate, and the ``joints.target`` echo apply. Effective rates above the
command worker's MAX_APPLY_HZ (50) are downsampled by its latest-wins
coalescing, which is kinematically benign for position streaming.
"""

from __future__ import annotations

import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource
from orca_ui.library import CONTINUOUS, WAYPOINTS, LibraryError

SPEEDS = (0.5, 1.0, 2.0)
WAYPOINT_SEGMENT_S = 1.5      # synthesized timing for waypoint/demo segments
WAYPOINT_RATE_HZ = 25.0
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


def _interpolate(waypoints: list[list[float]],
                 segment_s: float = WAYPOINT_SEGMENT_S,
                 rate_hz: float = WAYPOINT_RATE_HZ) -> tuple[list[list[float]], float]:
    """Expand sparse waypoints into linearly interpolated frames."""
    frames: list[list[float]] = []
    steps = max(int(segment_s * rate_hz), 1)
    for start, end in zip(waypoints, waypoints[1:]):
        for step in range(steps):
            alpha = (step + 1) / steps
            frames.append([
                a + (b - a) * alpha for a, b in zip(start, end)
            ])
    return (frames or list(waypoints)), rate_hz


def play_frames(ctx: OpContext, *, name: str, joint_ids: list[str],
                frames: list[list[float]], rate_hz: float,
                speed: float, loop: bool) -> dict:
    """Paced playback with pause/stop; returns {frames, cycles}."""
    total = len(frames)
    duration_s = total / (rate_hz * speed)
    dt = 1.0 / (rate_hz * speed)
    cycles = 0
    ctx.set_phase("playing", progress=0.0,
                  detail=f"{name} · {duration_s:.1f}s @ ×{speed:g}")
    ctx.log(f"playing {name}: {total} frames, {duration_s:.1f}s at ×{speed:g}"
            f"{' (loop)' if loop else ''}")

    while True:
        next_t = time.monotonic()
        last_progress = 0.0
        for index, row in enumerate(frames):
            ctx.check_stop()
            ctx.pause_point()
            angles = {j: float(v) for j, v in zip(joint_ids, row)
                      if v is not None}
            ctx.service.set_targets(angles, source=ControlSource.OPERATION)
            now = time.monotonic()
            if now - last_progress >= PROGRESS_EVERY_S or index == total - 1:
                ctx.set_progress((index + 1) / total)
                last_progress = now
            next_t += dt
            delay = next_t - time.monotonic()
            if delay > 0:
                ctx.sleep(delay)
        cycles += 1
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
            frames, rate_hz = _interpolate(data.get("waypoints") or [])
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
        cycles = int(params.get("cycles", 1))
        if not 1 <= cycles <= 10:
            raise ServiceError("cycles must be between 1 and 10")
        return {"name": name, "cycles": cycles}

    def run(self, ctx: OpContext) -> dict:
        service = ctx.service
        session = service.session
        if session is None:
            from orca_ui.hand.service import ServiceError
            raise ServiceError("hand not connected", status_code=503)
        keyframes = service.list_demos()[self.params["name"]]
        joint_ids = list(service.supervisor.config.joint_ids)
        waypoints = []
        for fractions in keyframes * self.params["cycles"]:
            pose = hand_ops.pose_from_fractions(session.hand, fractions)
            waypoints.append([pose.get(j) for j in joint_ids])
        frames, rate_hz = _interpolate(waypoints)
        return play_frames(
            ctx, name=self.params["name"], joint_ids=joint_ids,
            frames=frames, rate_hz=rate_hz, speed=1.0, loop=False,
        )

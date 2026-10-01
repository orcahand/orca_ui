"""Trajectory playback: the shared engine behind replay and demo.

The player owns frame pacing on the op thread and submits the latest frame
through ``service.set_targets(source=OPERATION)`` — full validation, torque
gate, and the ``joints.target`` echo apply. The command worker re-samples that
stream onto the joint-loop rate, so the frame rate here sets how faithfully the
commanded path reaches the loop.

Waypoint replay additionally *holds* at each captured pose until the hand
reaches it (see :func:`_hold_until_arrived`). Everything else here is
open-loop pacing: nothing else waits for the hand.
"""

from __future__ import annotations

import math
import time

import numpy as np

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource
from orca_ui.library import CONTINUOUS, MOTOR_WAYPOINTS, WAYPOINTS, LibraryError

SPEEDS = (0.5, 1.0, 2.0)
WAYPOINT_SPEED_DEG_S = 60.0   # cruise speed for synthesized waypoint segments
MIN_SEGMENT_S = 0.3           # floor so near-identical waypoints still glide
# Half the worker's feed rate — upsampling to the loop rate is its job, not
# this one's, and submitting faster only adds echo traffic and lock churn.
WAYPOINT_RATE_HZ = 100.0
LEAD_IN_MIN_DEG = 2.0         # skip the approach glide when already at start
PROGRESS_EVERY_S = 0.2
MAX_LOOP_CYCLES = 1000

# Stepped playback ("interp_steps"): N intermediate commands per segment
# instead of the cruise-speed glide — crisp point-to-point motion where the
# pacing knobs are speed and the per-command period. One command per
# INTERP_STEP_PERIOD_S at x1 unless "step_period_s" overrides it — with 0
# steps that period IS the waypoint-to-waypoint time: the motor's own
# controller does the travelling, the period just sets the rhythm.
INTERP_STEP_PERIOD_S = 0.1
MIN_STEP_PERIOD_S = 0.02      # 50 Hz — the bus keeps up, anything faster is churn
MAX_STEP_PERIOD_S = 5.0
MAX_INTERP_STEPS = 200
MIN_INTERP_STEPS = 1
# Seconds to let a chain reach a waypoint before giving up on it. Generous:
# this bounds a motor that cannot arrive, it does not pace one that can.
WAYPOINT_ARRIVAL_TIMEOUT_S = 5.0

# Waypoint holds. The hand trails the command stream by its own tracking lag
# (~100 ms on a motors-only hand, more on a loaded thumb), while a waypoint is
# commanded for a single frame period — so without a hold every corner is
# rounded and the poses that were captured at full flexion are never made.
# Bounded at both ends: a floor so the mechanics settle even when the sampled
# pose already agrees, and a cap so a joint that cannot reach its target slows
# playback down instead of stalling it.
DWELL_TOLERANCE_DEG = 1.5
DWELL_STILL_DEG = 0.3         # per poll: movement below this is "stopped"
DWELL_MIN_S = 0.15
DWELL_MAX_S = 1.0
DWELL_POLL_S = 0.05


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


def _interpolate(
    waypoints: list[list[float]], rate_hz: float = WAYPOINT_RATE_HZ,
) -> tuple[list[list[float]], float, list[int]]:
    """Expand sparse waypoints into linearly interpolated frames.

    Returns the frames, their rate, and the indices of the frames that land
    exactly on a waypoint — where waypoint replay holds. The list opens on
    the first waypoint (segments emit only the frames *after* their start),
    so the pose the recording starts from is held like every other one.
    """
    if not waypoints:
        return [], rate_hz, []
    frames: list[list[float]] = [list(waypoints[0])]
    holds = [0]
    for start, end in zip(waypoints, waypoints[1:]):
        frames.extend(_segment_frames(start, end, rate_hz))
        holds.append(len(frames) - 1)
    return frames, rate_hz, holds


def _lead_in(service, joint_ids: list[str],
             first_row: list, rate_hz: float) -> list[list[float]]:
    """Approach glide from the hand's current pose to the first frame.

    Without it, the first command of playback jumps the hand from wherever
    it currently is at full motor speed. Empty when the pose is unknown or
    already within LEAD_IN_MIN_DEG of the start.

    Reads the session's joint source rather than the encoders alone: a hand
    without joint encoders has a calibrated motor estimate, which is what it
    recorded from.
    """
    session = service.session
    sampled = (session.sampled_joints() or {}) if session else {}
    start = [sampled.get(j) for j in joint_ids]
    deltas = [abs(b - a) for a, b in zip(start, first_row)
              if a is not None and b is not None]
    if max(deltas, default=0.0) < LEAD_IN_MIN_DEG:
        return []
    return _segment_frames(start, first_row, rate_hz)


def _arrived(sampled: dict | None, angles: dict[str, float],
             previous: dict | None) -> bool:
    """True once the hand is at the pose, or has stopped approaching it.

    Two exits, because a tendon-driven joint does not always reach its
    target: inside DWELL_TOLERANCE_DEG is arrival, and having stopped moving
    between polls means this is as close as the joint gets (tendon stretch,
    a current limit, slack). Without the second one a single stiff joint —
    a loose thumb is enough — runs every hold to its cap.

    ``sampled`` is the same source a recording samples: encoders, else the
    calibrated motor estimate, so a replayed pose is compared against the
    recorded one in the units it was captured in. Nothing to read means
    nothing to confirm, and the hold runs to its cap.
    """
    if not sampled:
        return False
    errors = [abs(sampled[joint] - target)
              for joint, target in angles.items() if joint in sampled]
    if not errors:
        return False
    if max(errors) <= DWELL_TOLERANCE_DEG:
        return True
    if not previous:
        return False
    moved = [abs(sampled[joint] - previous[joint]) for joint in angles
             if joint in sampled and joint in previous]
    return bool(moved) and max(moved) <= DWELL_STILL_DEG


def _hold_until_arrived(ctx: OpContext, angles: dict[str, float]) -> None:
    """Sit on a commanded waypoint until the hand gets there.

    A waypoint recording is a sequence of *static* poses — each one captured
    while the hand was held still — so replay has to stop at each one. The
    frame stream on its own reaches a waypoint for a single frame period
    while the hand is still travelling towards the previous one.
    """
    ctx.sleep(DWELL_MIN_S)
    deadline = time.monotonic() + max(DWELL_MAX_S - DWELL_MIN_S, 0.0)
    previous: dict | None = None
    while time.monotonic() < deadline:
        ctx.check_stop()
        ctx.pause_point()
        session = ctx.service.session
        sampled = session.sampled_joints() if session is not None else None
        if _arrived(sampled, angles, previous):
            return
        previous = sampled
        ctx.sleep(DWELL_POLL_S)


def _stream(ctx: OpContext, joint_ids: list[str], frames: list[list[float]],
            dt: float, progress=None, holds: "list[int] | tuple" = ()) -> None:
    """Command frames at a fixed cadence, honoring pause/stop.

    ``holds`` names frame indices to sit on until the hand arrives; the
    cadence grid restarts afterwards, since the hold just broke it.
    """
    hold_at = set(holds)
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
        if index in hold_at:
            _hold_until_arrived(ctx, angles)
            next_t = time.monotonic()
        next_t += dt
        delay = next_t - time.monotonic()
        if delay > 0:
            ctx.sleep(delay)


def _lerp(a, b, fraction: float):
    """Linear step tolerant of None entries (a joint some frames omit)."""
    if a is None or b is None:
        return b if fraction >= 1.0 else None
    return a + (b - a) * fraction


def _stepped_frames(waypoints: list, steps: int) -> list:
    """Frames for each segment, ``steps`` of them, the last being the endpoint.

    ``steps=1`` is a direct move: the only command issued for a segment is its
    endpoint, and the servo's own trajectory generator does the travelling.
    Nothing is split beyond what was asked for -- a segment the operator
    recorded as one move stays one move.
    """
    steps = max(MIN_INTERP_STEPS, int(steps))
    frames = [list(waypoints[0])]
    for start, end in zip(waypoints, waypoints[1:]):
        for k in range(1, steps + 1):
            fraction = k / steps
            frames.append([_lerp(a, b, fraction)
                           for a, b in zip(start, end)])
    return frames


def _await_arrival(ctx: OpContext, hand, what: str) -> None:
    """Block until every motor has settled, or say why it did not.

    A motor held short of its goal never reports arrival, so this is logged
    rather than raised: stopping playback outright would be a worse answer
    than carrying on from where the hand actually is.
    """
    from orca_core.hardware.motor_client import MotionTimeoutError

    try:
        hand.wait_for_motion(timeout=WAYPOINT_ARRIVAL_TIMEOUT_S)
    except MotionTimeoutError as exc:
        ctx.log(f"{what}: not every motor arrived within "
                f"{WAYPOINT_ARRIVAL_TIMEOUT_S:g}s ({exc})")


def play_frames(ctx: OpContext, *, name: str, joint_ids: list[str],
                frames: list[list[float]], rate_hz: float,
                speed: float, loop: bool,
                holds: "list[int] | tuple" = ()) -> dict:
    """Paced playback with pause/stop; returns {frames, cycles}.

    ``duration_s`` counts the commanded motion only — waypoint holds add to
    the wall clock on top of it, by however long the hand takes to arrive.
    """
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
    if holds:
        ctx.log(f"holding at {len(holds)} waypoint(s) until the hand arrives "
                f"(≤{DWELL_MAX_S:g}s each)")

    while True:
        _stream(ctx, joint_ids, frames, dt, progress=ctx.set_progress,
                holds=holds)
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
        traj_type = meta.get("type")
        if traj_type not in (CONTINUOUS, WAYPOINTS, MOTOR_WAYPOINTS):
            raise ServiceError(f"unsupported trajectory type: {traj_type!r}")
        if meta.get("hand_type") not in (None, config.type):
            raise ServiceError(
                f"recorded for hand_type={meta.get('hand_type')}, "
                f"connected is {config.type}")
        if traj_type == MOTOR_WAYPOINTS:
            # Raw motor coordinates are only portable under a completed
            # calibration (limits + wrap offsets define the frame). On the
            # same hand in the same power cycle they are self-consistent,
            # so an explicit override may replay them uncalibrated.
            if not getattr(service.session.hand, "calibrated", False) and \
                    not bool(params.get("allow_uncalibrated")):
                raise ServiceError(
                    "motor-waypoint replay needs a calibrated hand — "
                    "calibrate first, or pass allow_uncalibrated if the "
                    "recording was made on this hand in its current state",
                    status_code=409)
            recorded_motors = [int(m) for m in (meta.get("motor_ids") or [])]
            if recorded_motors != [int(m) for m in config.motor_ids]:
                raise ServiceError(
                    "recorded motor order does not match the connected "
                    "hand config")
        else:
            recorded_ids = meta.get("joint_ids")
            if recorded_ids is not None and \
                    list(recorded_ids) != list(config.joint_ids):
                raise ServiceError(
                    "replay joint order does not match the connected hand "
                    "config")
        if traj_type == CONTINUOUS and not meta.get("sampling_frequency_hz"):
            raise ServiceError("continuous recording is missing sampling_frequency_hz")

        speed = float(params.get("speed", 1.0))
        if speed not in SPEEDS:
            raise ServiceError(f"speed must be one of {sorted(SPEEDS)}")
        interp_steps = params.get("interp_steps")
        if interp_steps is not None:
            interp_steps = int(interp_steps)
            if not MIN_INTERP_STEPS <= interp_steps <= MAX_INTERP_STEPS:
                raise ServiceError(
                    f"interp_steps must be {MIN_INTERP_STEPS}.."
                    f"{MAX_INTERP_STEPS} ({MIN_INTERP_STEPS} = move directly "
                    f"from each waypoint to the next)")
            if traj_type == CONTINUOUS:
                raise ServiceError(
                    "interp_steps applies to waypoint recordings — a "
                    "continuous recording carries its own timing")
        step_period = params.get("step_period_s")
        if step_period is not None:
            step_period = float(step_period)
            if not MIN_STEP_PERIOD_S <= step_period <= MAX_STEP_PERIOD_S:
                raise ServiceError(
                    f"step_period_s must be {MIN_STEP_PERIOD_S:g}.."
                    f"{MAX_STEP_PERIOD_S:g} seconds")
            if traj_type == CONTINUOUS:
                raise ServiceError(
                    "step_period_s applies to waypoint recordings — a "
                    "continuous recording carries its own timing")
            if traj_type == WAYPOINTS and interp_steps is None:
                raise ServiceError(
                    "step_period_s paces stepped playback — set interp_steps "
                    "too (0 = straight to each waypoint)")
        frames = data.get("angles") or data.get("waypoints") or []
        if not frames:
            raise ServiceError("trajectory contains no frames")
        return {
            "name": str(name),
            "speed": speed,
            "loop": bool(params.get("loop", False)),
            "type": traj_type,
            "interp_steps": interp_steps,
            # None = the INTERP_STEP_PERIOD_S default; only meaningful in
            # stepped/motor playback, where it is the seconds per command.
            "step_period_s": step_period,
        }

    def run(self, ctx: OpContext) -> dict:
        if self.params["type"] == MOTOR_WAYPOINTS:
            return self._run_motor_waypoints(ctx)
        data = ctx.service.library.load_trajectory(self.params["name"])
        meta = data.get("metadata") or {}
        joint_ids = list(meta.get("joint_ids")
                         or ctx.service.supervisor.config.joint_ids)
        interp_steps = self.params.get("interp_steps")
        if meta.get("type") == CONTINUOUS:
            # A continuous recording carries its own timing: every frame is a
            # sample of a hand in motion, so there is no pose to hold.
            frames = data.get("angles") or []
            rate_hz = float(meta["sampling_frequency_hz"])
            holds: list[int] = []
        else:
            waypoints = data.get("waypoints") or []
            # Close the cycle when looping so the wrap-around glides back
            # to the first waypoint instead of jumping at motor speed.
            if self.params["loop"] and len(waypoints) > 1:
                waypoints = waypoints + [list(waypoints[0])]
            if interp_steps is not None:
                # Stepped mode: N linear commands per segment, no holds —
                # crisp point-to-point paced by speed and the step period.
                frames = _stepped_frames(waypoints, interp_steps)
                rate_hz = 1.0 / (self.params["step_period_s"]
                                 or INTERP_STEP_PERIOD_S)
                holds: list[int] = []
            else:
                frames, rate_hz, holds = _interpolate(waypoints)
                if self.params["loop"] and len(holds) > 1:
                    # The closing waypoint is the next cycle's opening one,
                    # which is held there; holding it twice doubles the dwell.
                    holds = holds[:-1]
        return play_frames(
            ctx, name=self.params["name"], joint_ids=joint_ids,
            frames=frames, rate_hz=rate_hz,
            speed=self.params["speed"], loop=self.params["loop"],
            holds=holds,
        )

    def _run_motor_waypoints(self, ctx: OpContext) -> dict:
        """Raw motor-space stepping: pause the feedback loop's writes (the
        direct-motor fence), glide to the first waypoint, then command each
        (optionally interpolated) motor pose directly."""
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        data = service.library.load_trajectory(self.params["name"])
        meta = data.get("metadata") or {}
        motor_ids = [int(m) for m in meta.get("motor_ids") or []]
        waypoints = [[float(v) for v in row]
                     for row in data.get("waypoints") or []]
        if not motor_ids or not waypoints:
            raise ServiceError("motor recording is empty")
        loop = self.params["loop"]
        steps = max(MIN_INTERP_STEPS,
                    int(self.params.get("interp_steps") or MIN_INTERP_STEPS))
        if loop and len(waypoints) > 1:
            waypoints = waypoints + [list(waypoints[0])]
        period = self.params["step_period_s"] or INTERP_STEP_PERIOD_S
        dt = period / self.params["speed"]
        hand = session.hand
        name = self.params["name"]
        if not getattr(hand, "calibrated", False):
            ctx.log("hand is NOT calibrated — replaying raw motor positions "
                    "as recorded; only valid on the hand and power cycle "
                    "they were captured on")

        service.set_direct_motor_mode(True, from_operation=True)
        try:
            # The approach is a move to a waypoint like any other: one
            # command, then wait for the chain to get there.
            ctx.set_phase("approach", detail=f"{name} · moving to start")
            ctx.check_stop()
            ctx.pause_point()
            hand.write_motor_pos(
                motor_ids, np.asarray(waypoints[0], dtype=float))
            _await_arrival(ctx, hand, "start")

            # The hardware motor client divides positions by its scale, so
            # rows must be arrays, not plain lists.
            frames = [np.asarray(row, dtype=float)
                      for row in _stepped_frames(waypoints, steps)]
            total = len(frames)
            duration_s = total * dt
            cycles = 0
            ctx.set_phase("playing", progress=0.0,
                          detail=f"{name} · motor stepping @ "
                                 f"×{self.params['speed']:g}")
            ctx.log(f"playing {name}: {len(waypoints)} motor waypoints, "
                    f"{total} commands at {dt * 1000:.0f} ms each"
                    f"{' (loop)' if loop else ''}")
            last_progress = 0.0
            while True:
                # frames[0] restates where the approach already put the hand.
                for index, row in enumerate(frames[1:], start=1):
                    ctx.check_stop()
                    ctx.pause_point()
                    hand.write_motor_pos(motor_ids, row)
                    now = time.monotonic()
                    if now - last_progress >= PROGRESS_EVERY_S or \
                            index == total - 1:
                        ctx.set_progress((index + 1) / total)
                        last_progress = now
                    if index % steps:
                        # Mid-segment, so only a step on the way somewhere.
                        ctx.sleep(dt)
                    else:
                        # A recorded waypoint, and so a sync point: no motor
                        # starts the next leg until every motor has finished
                        # this one.
                        _await_arrival(ctx, hand, f"waypoint {index // steps}")
                        ctx.sleep(dt)
                cycles += 1
                if loop and cycles >= MAX_LOOP_CYCLES:
                    ctx.log(f"loop backstop reached ({MAX_LOOP_CYCLES} "
                            "cycles) — stopping playback")
                if not loop or cycles >= MAX_LOOP_CYCLES:
                    return {"frames": len(waypoints), "cycles": cycles,
                            "duration_s": duration_s}
                ctx.set_detail(f"{name} · cycle {cycles + 1}")
        finally:
            service.set_direct_motor_mode(False, from_operation=True)


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
        frames, rate_hz, _holds = _interpolate(waypoints)
        # Demos do not hold at keyframes: they are continuous flourishes, not
        # separately captured poses.
        return play_frames(
            ctx, name=self.params["name"], joint_ids=joint_ids,
            frames=frames, rate_hz=rate_hz, speed=1.0,
            loop=self.params["loop"],
        )

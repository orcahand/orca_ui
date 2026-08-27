"""Cable-integrity stress test: drive selected joints end-to-end, repeatedly.

An endurance run, not a demo. The picked joints are commanded to one end of
their configured ROM and then the other, over and over, holding at each
extreme until the hand actually arrives — which is the point: a tendon that
has stretched or a cable that has started to slip stops reaching the end it
was told to go to, and that shows up as a shrinking travel span long before
anything snaps. Joints that were not picked are never commanded, so they
stay wherever the last owner of the target channel left them.

Motion reuses the player's primitives (segment pacing, the frame streamer,
the arrival hold) so a stress cycle moves exactly like a replayed waypoint
pair — same cruise speed, same pause/stop behaviour, same tracking
assumptions. The cycle loop lives here because the run is counted in cycles,
not frames, and can be far longer than any recording.
"""

from __future__ import annotations

from orca_ui.hand.operations.base import OpContext, Operation

# Sibling-module reuse: these are the player's movement primitives, private
# to the package rather than to the module (test_playback imports its
# _interpolate the same way). Duplicating them here is what we are avoiding.
from orca_ui.hand.operations.player import (
    SPEEDS,
    WAYPOINT_RATE_HZ,
    _hold_until_arrived,
    _lead_in,
    _require_playable,
    _segment_frames,
    _stream,
)
from orca_ui.hand.states import ControlSource

DEFAULT_CYCLES = 20
MAX_CYCLES = 1000        # also the backstop for a nonstop run
DEFAULT_HOLD_S = 0.25    # extra dwell at each extreme, on top of the arrival hold
MAX_HOLD_S = 5.0
MAX_MARGIN_DEG = 15.0    # back-off from each hardstop, for a gentler run
MIN_TRAVEL_DEG = 2.0     # a margin leaving less than this is a mistake, not a test


class _ReachTracker:
    """How far the hand actually gets at each end of the range.

    Sampled once per extreme, *after* the arrival hold, so the value is a
    settled position rather than one caught mid-travel. ``span`` — how much
    travel the joint achieved between its two settled extremes — is the
    number worth watching: it shrinks as a tendon stretches. Nothing is
    recorded on a hand with no joint-angle source; the run still happens,
    the report just says so.
    """

    def __init__(self, joints: list[str], lo: list[float], hi: list[float]):
        self.joints = list(joints)
        self.lo = {j: v for j, v in zip(joints, lo)}
        self.hi = {j: v for j, v in zip(joints, hi)}
        self.settled: dict[str, dict[str, float]] = {}   # joint -> {min, max}
        self.worst: dict[str, float] = {}                # joint -> worst shortfall
        self.samples = 0

    def sample(self, ctx: OpContext, end: str) -> None:
        session = ctx.service.session
        sampled = session.sampled_joints() if session is not None else None
        if not sampled:
            return
        self.samples += 1
        for joint in self.joints:
            measured = sampled.get(joint)
            if measured is None:
                continue
            self.settled.setdefault(joint, {})[end] = float(measured)
            # Shortfall at this end: how far short of the commanded extreme
            # the joint settled. Overshoot is not a cable problem — floor it.
            target = self.hi[joint] if end == "max" else self.lo[joint]
            short = (target - measured) if end == "max" else (measured - target)
            short = max(float(short), 0.0)
            self.worst[joint] = max(self.worst.get(joint, 0.0), short)

    def report(self) -> list[dict]:
        out = []
        for joint in self.joints:
            commanded = self.hi[joint] - self.lo[joint]
            ends = self.settled.get(joint) or {}
            reached_min = ends.get("min")
            reached_max = ends.get("max")
            span = (
                reached_max - reached_min
                if reached_min is not None and reached_max is not None
                else None
            )
            out.append({
                "id": joint,
                "target": [self.lo[joint], self.hi[joint]],
                "commanded_span_deg": commanded,
                "reached": (
                    [reached_min, reached_max]
                    if span is not None else None
                ),
                "span_deg": span,
                # Travel the joint is missing against what it was commanded.
                "span_shortfall_deg": (
                    commanded - span if span is not None else None
                ),
                # Worst single-end miss seen across the whole run.
                "worst_shortfall_deg": self.worst.get(joint),
            })
        return out


class StressTestOperation(Operation):
    kind = "stress_test"
    control_source = ControlSource.OPERATION

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        _require_playable(service)
        config = service.supervisor.config

        raw = params.get("joints")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ServiceError("pick at least one joint to stress test")
        picked = {str(j) for j in raw}
        unknown = picked - set(config.joint_ids)
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        # Config order, deduped — the run reads the same way whatever order
        # the checkboxes were ticked in.
        joints = [j for j in config.joint_ids if j in picked]
        unmapped = [j for j in joints
                    if config.joint_to_motor_map.get(j) is None]
        if unmapped:
            raise ServiceError(
                f"no motor drives {', '.join(unmapped)} — "
                "it cannot be moved")

        margin = float(params.get("margin_deg", 0.0))
        if not 0.0 <= margin <= MAX_MARGIN_DEG:
            raise ServiceError(f"margin_deg must be 0..{MAX_MARGIN_DEG:g}")
        cramped = [
            j for j in joints
            if (float(config.joint_roms_dict[j][1]) - margin)
            - (float(config.joint_roms_dict[j][0]) + margin) < MIN_TRAVEL_DEG
        ]
        if cramped:
            raise ServiceError(
                f"a {margin:g}° margin leaves less than {MIN_TRAVEL_DEG:g}° "
                f"of travel on {', '.join(cramped)}")

        speed = float(params.get("speed", 1.0))
        if speed not in SPEEDS:
            raise ServiceError(f"speed must be one of {sorted(SPEEDS)}")
        loop = bool(params.get("loop", False))
        cycles = int(params.get("cycles", DEFAULT_CYCLES))
        if not loop and not 1 <= cycles <= MAX_CYCLES:
            raise ServiceError(f"cycles must be between 1 and {MAX_CYCLES}")
        hold_s = float(params.get("hold_s", DEFAULT_HOLD_S))
        if not 0.0 <= hold_s <= MAX_HOLD_S:
            raise ServiceError(f"hold_s must be 0..{MAX_HOLD_S:g}")

        return {
            "joints": joints,
            "cycles": MAX_CYCLES if loop else cycles,
            "loop": loop,
            "speed": speed,
            "hold_s": hold_s,
            "margin_deg": margin,
        }

    def run(self, ctx: OpContext) -> dict:
        config = ctx.service.supervisor.config
        joints = self.params["joints"]
        margin = self.params["margin_deg"]
        speed = self.params["speed"]
        loop = self.params["loop"]
        cycles = self.params["cycles"]
        hold_s = self.params["hold_s"]

        lo_target, hi_target = [], []
        for joint in joints:
            lo, hi = (float(v) for v in config.joint_roms_dict[joint])
            lo_target.append(lo + margin)
            hi_target.append(hi - margin)
        tracker = _ReachTracker(joints, lo_target, hi_target)

        ctx.log(
            f"stress test: {len(joints)} joint(s), "
            f"{'nonstop' if loop else f'{cycles} cycle(s)'} at ×{speed:g}"
            + (f", {margin:g}° off each hardstop" if margin else ""))
        for joint, lo, hi in zip(joints, lo_target, hi_target):
            ctx.log(f"  {joint}: {lo:.1f}° ↔ {hi:.1f}° ({hi - lo:.1f}° travel)")

        # Approach the low end at cruise pacing before the count starts —
        # the same glide replay uses, so cycle 1 is not a jump from wherever
        # the hand happens to be sitting.
        approach = _lead_in(ctx.service, joints, lo_target, WAYPOINT_RATE_HZ)
        if approach:
            ctx.set_phase("approach", detail="moving to the start of the range")
            _stream(ctx, joints, approach, 1.0 / WAYPOINT_RATE_HZ)
        self._settle(ctx, joints, lo_target, hold_s, tracker, "min")

        dt = 1.0 / (WAYPOINT_RATE_HZ * speed)
        legs = None if loop else cycles * 2
        done = 0
        completed = 0
        current = list(lo_target)
        ctx.set_phase("cycling", progress=None if legs is None else 0.0)
        ctx.set_extra(self._extra(tracker, 0, cycles, loop))

        while True:
            for end, target in (("max", hi_target), ("min", lo_target)):
                ctx.set_detail(
                    f"cycle {completed + 1}"
                    f"{'' if loop else f'/{cycles}'} → {end}")
                frames = _segment_frames(current, target, WAYPOINT_RATE_HZ)
                _stream(ctx, joints, frames, dt,
                        progress=self._leg_progress(ctx, done, legs))
                current = list(target)
                self._settle(ctx, joints, target, hold_s, tracker, end)
                done += 1
                if legs is not None:
                    ctx.set_progress(done / legs)
                # Per leg, not per cycle: a run stopped part-way through its
                # first cycle should still show what it managed to measure.
                ctx.set_extra(self._extra(tracker, completed, cycles, loop))
            completed += 1
            ctx.set_extra(self._extra(tracker, completed, cycles, loop))
            if completed >= cycles:
                if loop:
                    ctx.log(f"loop backstop reached ({MAX_CYCLES} cycles) — "
                            "stopping the stress test")
                break

        report = tracker.report()
        self._log_report(ctx, report, completed)
        return {
            "cycles": completed,
            "joints": joints,
            "speed": speed,
            "margin_deg": margin,
            "measured": tracker.samples > 0,
            "report": report,
        }

    # ----- helpers ------------------------------------------------------------

    @staticmethod
    def _leg_progress(ctx: OpContext, done: int, legs: int | None):
        """Map a segment's 0..1 progress onto the whole run's, or None when
        the run is nonstop and has no total to divide by."""
        if legs is None:
            return None
        return lambda fraction: ctx.set_progress((done + fraction) / legs)

    def _settle(self, ctx: OpContext, joints: list[str], target: list[float],
                hold_s: float, tracker: _ReachTracker, end: str) -> None:
        """Sit on an extreme until the hand arrives (or stops approaching),
        dwell for the configured hold, then record where it actually got to."""
        _hold_until_arrived(ctx, dict(zip(joints, target)))
        if hold_s > 0:
            ctx.sleep(hold_s)
        tracker.sample(ctx, end)

    @staticmethod
    def _extra(tracker: _ReachTracker, completed: int, cycles: int,
               loop: bool) -> dict:
        return {
            "cycle": completed,
            "cycles": cycles,
            "loop": loop,
            "measured": tracker.samples > 0,
            "joints": tracker.report(),
        }

    @staticmethod
    def _log_report(ctx: OpContext, report: list[dict], completed: int) -> None:
        ctx.log(f"{completed} cycle(s) done")
        for row in report:
            if row["span_deg"] is None:
                ctx.log(f"  {row['id']}: no joint-angle source — travel "
                        "not measured")
                continue
            ctx.log(
                f"  {row['id']}: reached {row['reached'][0]:.1f}° ↔ "
                f"{row['reached'][1]:.1f}° = {row['span_deg']:.1f}° of "
                f"{row['commanded_span_deg']:.1f}° commanded "
                f"({row['span_shortfall_deg']:+.1f}°)")

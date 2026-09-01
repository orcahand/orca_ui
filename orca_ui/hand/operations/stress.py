"""Cable-integrity stress test: drive selected joints end-to-end, repeatedly.

An endurance run, not a demo. The picked joints are commanded to one end of
their configured ROM and then the other, over and over, holding at each
extreme until the hand actually arrives — which is the point: a tendon that
has stretched or a cable that has started to slip stops reaching the end it
was told to go to, and that shows up as a shrinking travel span long before
anything snaps. Joints that were not picked are never commanded, so they
stay wherever the last owner of the target channel left them.

``hold_rest`` changes that: every unpicked joint is instead parked at its
outward ROM limit and held there for the whole run, which is how you stress
one joint pair — the thumb MCP and DIP, say — with the rest of the hand
splayed clear of it rather than drifting into its path. ``freeze_abduction``
keeps the abduction joints out of that parked set, so a fan-out that would
strain a spread the hand is not in stays off while the rest still holds.

The thumb runs in counter-phase by default: it opens as the fingers close
and closes as they open. In phase the whole hand balls up, the thumb lands
inside the closing fingers and the two fight each other — which loads the
tendons against the wrong thing and tells you nothing about the cables.
Opposed, the thumb travels through free space and the run stresses each
tendon against its own routing.

Motion reuses the player's primitives (segment pacing, the frame streamer,
the arrival hold) so a stress cycle moves exactly like a replayed waypoint
pair — same cruise speed, same pause/stop behaviour, same tracking
assumptions. The cycle loop lives here because the run is counted in cycles,
not frames, and can be far longer than any recording.

``interp_steps`` picks how a leg is commanded, with replay's semantics:
omitted glides at cruise speed, an integer sends that many intermediate
commands per leg, and 0 sends the endpoint alone — one write, and the motors
travel the whole range at their own speed. Zero is the harshest setting the
test has and the one that shows up a marginal cable fastest; every mode
still holds at the extreme until the hand arrives.
"""

from __future__ import annotations

from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.hand_ops import FINGER_TO_JOINTS

# Sibling-module reuse: these are the player's movement primitives, private
# to the package rather than to the module (test_playback imports its
# _interpolate the same way). Duplicating them here is what we are avoiding.
from orca_ui.hand.operations.player import (
    INTERP_STEP_PERIOD_S,
    MAX_INTERP_STEPS,
    MAX_STREAM_HZ,
    SPEEDS,
    WAYPOINT_RATE_HZ,
    _hold_until_arrived,
    _lead_in,
    _require_playable,
    _segment_frames,
    _stepped_frames,
    _stream,
)
from orca_ui.hand.states import ControlSource

DEFAULT_CYCLES = 20
MAX_CYCLES = 100_000_000  # also the backstop for a nonstop run
DEFAULT_HOLD_S = 0.25    # extra dwell at each extreme, on top of the arrival hold
MAX_HOLD_S = 5.0
MAX_MARGIN_DEG = 15.0    # back-off from each hardstop, for a gentler run
MIN_TRAVEL_DEG = 2.0     # a margin leaving less than this is a mistake, not a test

# The joints that swap phase. Taken from the shared finger map rather than a
# name prefix so it stays right if a hand config names them differently.
THUMB_JOINTS = frozenset(FINGER_TO_JOINTS["thumb"])

ABDUCTION_SUFFIX = "_abd"
# Abduction fans apart rather than extending: ring and pinky swing towards the
# high end of their range, index towards the low one, and the middle finger has
# no outward side at all so it parks centred. Mirrors orca_core's `fan_out`.
_ABD_PARK_HIGH = frozenset({"ring_abd", "pinky_abd"})
_ABD_PARK_CENTRED = frozenset({"middle_abd"})

# The two poses a cycle alternates between. "flexed" is the upper end of each
# joint's ROM and "extended" the lower — except for an opposed thumb, which
# takes the opposite end of its own range in each.
FLEXED = "flexed"
EXTENDED = "extended"


def _park_angle(joint: str, lo: float, hi: float) -> float:
    """Where an unpicked joint is held while the picked ones cycle.

    "Outwards" is not the same end of the ROM for every joint. Flexion joints
    extend towards the low end; every thumb joint opens towards the high one;
    the abduction joints fan apart per _ABD_PARK_*. Bounds are already
    margin-adjusted by the caller, so this only picks an end.
    """
    if joint in _ABD_PARK_CENTRED:
        return (lo + hi) / 2.0
    if joint in THUMB_JOINTS or joint in _ABD_PARK_HIGH:
        return hi
    return lo


def _leg_description(interp_steps: int | None) -> str:
    if interp_steps is None:
        return "each leg glides at cruise speed"
    if interp_steps == 0:
        return ("each leg is one command straight to the extreme — the motors "
                "run the whole range at their own speed")
    return (f"each leg is {interp_steps} intermediate command(s) plus the "
            "extreme")


class _ReachTracker:
    """How far the hand actually gets at each end of the range.

    Sampled once per extreme, *after* the arrival hold, so the value is a
    settled position rather than one caught mid-travel. ``span`` — how much
    travel the joint achieved between its two settled extremes — is the
    number worth watching: it shrinks as a tendon stretches. Nothing is
    recorded on a hand with no joint-angle source; the run still happens,
    the report just says so.

    Ends are worked out per joint from the angle it was actually commanded,
    not from which leg of the cycle this is — a counter-phase thumb is at its
    lower end while everything else is at its upper one.
    """

    def __init__(self, joints: list[str], lo: dict[str, float],
                 hi: dict[str, float]):
        self.joints = list(joints)
        self.lo = dict(lo)
        self.hi = dict(hi)
        self.settled: dict[str, dict[str, float]] = {}   # joint -> {min, max}
        self.worst: dict[str, float] = {}                # joint -> worst shortfall
        self.samples = 0

    def sample(self, ctx: OpContext, targets: dict[str, float]) -> None:
        session = ctx.service.session
        sampled = session.sampled_joints() if session is not None else None
        if not sampled:
            return
        self.samples += 1
        for joint in self.joints:
            measured = sampled.get(joint)
            target = targets.get(joint)
            if measured is None or target is None:
                continue
            # Which end of ITS OWN range this joint was sent to.
            upper = abs(target - self.hi[joint]) <= abs(target - self.lo[joint])
            self.settled.setdefault(joint, {})["max" if upper else "min"] = \
                float(measured)
            # Shortfall at this end: how far short of the commanded extreme
            # the joint settled. Overshoot is not a cable problem — floor it.
            short = (target - measured) if upper else (measured - target)
            self.worst[joint] = max(self.worst.get(joint, 0.0),
                                    max(float(short), 0.0))

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
        interp_steps = params.get("interp_steps")
        if interp_steps is not None:
            interp_steps = int(interp_steps)
            if not 0 <= interp_steps <= MAX_INTERP_STEPS:
                raise ServiceError(
                    f"interp_steps must be 0..{MAX_INTERP_STEPS} "
                    "(0 = straight to the extreme at motor speed), or "
                    "omitted for the cruise-speed glide")

        return {
            "joints": joints,
            "cycles": MAX_CYCLES if loop else cycles,
            "loop": loop,
            "speed": speed,
            "hold_s": hold_s,
            "margin_deg": margin,
            # None = cruise-speed glide; an integer = that many intermediate
            # commands per leg, 0 being a single write to the extreme.
            "interp_steps": interp_steps,
            # Opposition is the default; turn it off to drive every picked
            # joint to the same end of its range at the same time.
            "thumb_opposed": bool(params.get("thumb_opposed", True)),
            # Park every joint that was not picked at its outward ROM limit
            # and hold it there for the whole run, instead of leaving it
            # wherever the last owner of the target channel left it.
            "hold_rest": bool(params.get("hold_rest", False)),
            # Keep the abduction joints out of that parked set, so they hold
            # where they already are rather than being fanned out.
            "freeze_abduction": bool(params.get("freeze_abduction", False)),
        }

    def run(self, ctx: OpContext) -> dict:
        config = ctx.service.supervisor.config
        joints = self.params["joints"]
        margin = self.params["margin_deg"]
        speed = self.params["speed"]
        loop = self.params["loop"]
        cycles = self.params["cycles"]
        hold_s = self.params["hold_s"]
        interp_steps = self.params["interp_steps"]

        lo: dict[str, float] = {}
        hi: dict[str, float] = {}
        for joint in joints:
            low, high = (float(v) for v in config.joint_roms_dict[joint])
            lo[joint], hi[joint] = low + margin, high - margin
        tracker = _ReachTracker(joints, lo, hi)

        # Joints held fully outwards for the whole run. They are streamed in
        # every frame alongside the cycling ones — same value in both poses,
        # so they glide out during the approach and then stay put — but stay
        # out of the tracker, which reports on what was actually cycled.
        parked = self._parked_angles(config, joints, margin)

        # The two poses the cycle alternates between. An opposed thumb takes
        # the far end of its own range in each, so it extends into the pose
        # where every other joint flexes.
        opposed = sorted(
            j for j in joints if self.params["thumb_opposed"] and j in THUMB_JOINTS
        )
        stream_joints = joints + list(parked)
        park_row = list(parked.values())
        pose = {
            FLEXED: [lo[j] if j in opposed else hi[j] for j in joints] + park_row,
            EXTENDED: [hi[j] if j in opposed else lo[j] for j in joints] + park_row,
        }

        ctx.log(
            f"stress test: {len(joints)} joint(s), "
            f"{'nonstop' if loop else f'{cycles} cycle(s)'} at ×{speed:g}"
            + (f", {margin:g}° off each hardstop" if margin else ""))
        ctx.log(_leg_description(interp_steps))
        if opposed:
            ctx.log(f"thumb in counter-phase: {', '.join(opposed)} open as "
                    "the rest close, and close as they open")
        if parked:
            ctx.log(f"held fully outwards: {', '.join(parked)}")
        elif self.params["hold_rest"]:
            ctx.log("nothing left to hold outwards — every drivable joint "
                    "is being cycled")
        if self.params["freeze_abduction"]:
            ctx.log(f"abduction frozen: unpicked *{ABDUCTION_SUFFIX} joints "
                    "are not commanded")
        for joint in joints:
            ctx.log(f"  {joint}: {lo[joint]:.1f}° ↔ {hi[joint]:.1f}° "
                    f"({hi[joint] - lo[joint]:.1f}° travel"
                    + (", opposed)" if joint in opposed else ")"))

        # Approach the first pose at cruise pacing before the count starts —
        # the same glide replay uses, so cycle 1 is not a jump from wherever
        # the hand happens to be sitting.
        start = pose[EXTENDED]
        approach = _lead_in(ctx.service, stream_joints, start, WAYPOINT_RATE_HZ)
        if approach:
            ctx.set_phase("approach", detail="moving to the start of the range")
            _stream(ctx, stream_joints, approach, 1.0 / WAYPOINT_RATE_HZ)
        self._settle(ctx, stream_joints, start, hold_s, tracker)

        # Glide mode paces on the frame grid; stepped mode paces on replay's
        # command period. The glide rate is capped so a fast run submits at a
        # bounded cadence instead of flooding the joint loop (what
        # play_frames' stride does for a recording).
        glide_rate = min(WAYPOINT_RATE_HZ, MAX_STREAM_HZ / speed)
        dt = (1.0 / (glide_rate * speed) if interp_steps is None
              else INTERP_STEP_PERIOD_S / speed)
        legs = None if loop else cycles * 2
        done = 0
        completed = 0
        current = list(start)
        ctx.set_phase("cycling", progress=None if legs is None else 0.0)
        ctx.set_extra(self._extra(tracker, 0, cycles, loop, opposed))

        while True:
            for name in (FLEXED, EXTENDED):
                target = pose[name]
                ctx.set_detail(
                    f"cycle {completed + 1}"
                    f"{'' if loop else f'/{cycles}'} → {name}"
                    + (" (thumb opposed)" if opposed else ""))
                # Both builders are given [start, end] and drop the start:
                # the hand is already there.
                frames = (
                    _segment_frames(current, target, glide_rate)
                    if interp_steps is None
                    else _stepped_frames([current, target], interp_steps)[1:]
                )
                _stream(ctx, stream_joints, frames, dt,
                        progress=self._leg_progress(ctx, done, legs))
                current = list(target)
                self._settle(ctx, stream_joints, target, hold_s, tracker)
                done += 1
                if legs is not None:
                    ctx.set_progress(done / legs)
                # Per leg, not per cycle: a run stopped part-way through its
                # first cycle should still show what it managed to measure.
                ctx.set_extra(
                    self._extra(tracker, completed, cycles, loop, opposed))
            completed += 1
            ctx.set_extra(self._extra(tracker, completed, cycles, loop, opposed))
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
            "interp_steps": interp_steps,
            "opposed_joints": opposed,
            "held_joints": list(parked),
            "freeze_abduction": self.params["freeze_abduction"],
            "measured": tracker.samples > 0,
            "report": report,
        }

    # ----- helpers ------------------------------------------------------------

    def _parked_angles(self, config, joints: list[str],
                       margin: float) -> dict[str, float]:
        """Outward hold angle for every drivable joint that is not cycling.

        Empty unless ``hold_rest`` is set, which keeps the default behaviour:
        an unpicked joint is never commanded and stays wherever it was.
        """
        if not self.params["hold_rest"]:
            return {}
        cycling = set(joints)
        freeze = self.params["freeze_abduction"]
        parked: dict[str, float] = {}
        for joint in config.joint_ids:
            if joint in cycling or config.joint_to_motor_map.get(joint) is None:
                continue
            if freeze and joint.endswith(ABDUCTION_SUFFIX):
                continue
            low, high = (float(v) for v in config.joint_roms_dict[joint])
            parked[joint] = _park_angle(joint, low + margin, high - margin)
        return parked

    @staticmethod
    def _leg_progress(ctx: OpContext, done: int, legs: int | None):
        """Map a segment's 0..1 progress onto the whole run's, or None when
        the run is nonstop and has no total to divide by."""
        if legs is None:
            return None
        return lambda fraction: ctx.set_progress((done + fraction) / legs)

    def _settle(self, ctx: OpContext, joints: list[str], target: list[float],
                hold_s: float, tracker: _ReachTracker) -> None:
        """Sit on a pose until the hand arrives (or stops approaching), dwell
        for the configured hold, then record where it actually got to."""
        angles = dict(zip(joints, target))
        _hold_until_arrived(ctx, angles)
        if hold_s > 0:
            ctx.sleep(hold_s)
        tracker.sample(ctx, angles)

    @staticmethod
    def _extra(tracker: _ReachTracker, completed: int, cycles: int,
               loop: bool, opposed: list[str]) -> dict:
        return {
            "cycle": completed,
            "cycles": cycles,
            "loop": loop,
            "measured": tracker.samples > 0,
            "opposed_joints": list(opposed),
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

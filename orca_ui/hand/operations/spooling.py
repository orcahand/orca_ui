"""Spooling as a maintenance operation: attaching the tendons during assembly.

The bottom tendon of each motor is wound onto its bottom spool by hand, then
this operation takes over. Every motor is driven in its own positive shaft
direction — the direction a bare Dynamixel or Feetech servo turns for an
increasing position, before any joint mapping gives it a meaning — until the
finger sits on a hard stop. From there, three hand steps per motor:

- ``seating``: the motor keeps pulling at the winding current while the hand
  is wiggled to work the slack out of the bottom tendon, until the operator
  says it is done. The pull's goal never retreats, so a finger pushed back by
  hand is pulled back in at full current rather than followed.
- ``attaching``: the motor holds the hard-stop position at the winding
  current while the top tendon is run onto the top spool and pulled snug.
- ``tightening``: the current limit drops to the torque-wrench ceiling and
  the motor holds its anchor. Screwing the top spool in loads the motor until
  the screw's torque exceeds the cap and the shaft gives way — the same rule
  orca_core's ratchet rig uses to set a preload — and the motor is then "at
  torque": the frontend beeps and flashes green.

Two programs, chosen per run. ``all`` goes side by side, the way the pack
is assembled: one side's motors wind and seat together, then its top spools
go one at a time — the active motor is attached and tightened while the
others keep holding their anchor — then the other side; a finished motor
holds on at the tightening limit. ``one_by_one`` takes each
motor through all three steps before the next one starts. The spools are
visited side by side in motor-ID order — the pack has the finger motors on
two sides, lower IDs on one and higher on the other, with the wrist apart
(no spool, not tendon driven, never spooled) — and the motor whose spool is
up next wiggles so it can be found; a whole side can be wiggled too.

The run holds the maintenance lease and drives a motor-only hand from its own
tick loop, so a stop or e-stop lands between two bus commands and the
``finally`` always switches torque off. The console's motor health is offline
while the lease is held, so the loop reads temperatures itself: a motor near
its rated ceiling is dropped to a cool hold at its anchor until it recovers.

Snapshot ``extra``: ``{"mode", "phase", "tighten_current_ma", "limit_ma",
"max_temp_c", "active", "sides": [{"id", "label", "motor_ids"}], "motors":
[{"joint", "id", "side", "state", "current_ma", "limit_ma", "pushed_deg",
"temp_c", "done", "cooling"}]}`` with state one of ``pending | winding |
stalled | holding | reached | over``.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

logger = logging.getLogger(__name__)

MODES = ("all", "one_by_one")
WRIST = "wrist"

# The torque-wrench ceiling. A spool screwed in against more than this
# preloads the tendon pair beyond what the hand is built for, so no request
# may raise it — a higher ask is rejected, never clamped.
TIGHTEN_CURRENT_CEILING_MA = 100.0
MIN_TIGHTEN_CURRENT_MA = 10.0

TICK_S = 0.1
# While pulling, the goal is kept this far ahead of the shaft and never moves
# back: at a hard stop the position error saturates the servo at its current
# limit, and a finger pushed back by hand is pulled back in at full current.
WIND_LEAD_RAD = 0.6
# The servo's own velocity profile paces the pull, so the goal running ahead
# turns into one smooth motion rather than a step per tick.
WIND_VELOCITY_RAD_S = 2.0
WIND_ACCELERATION_RAD_S2 = 10.0
# The pull a half-built hand tolerates: at the operating current the motors
# pulled themselves out of their connectors on the bench.
DEFAULT_WIND_CURRENT_MA = 150.0
MIN_WIND_CURRENT_MA = 50.0
# Consecutive stale bus reads tolerated before the hold is abandoned.
MAX_READ_FAILURES = 20
# A motor far from its goal that draws nothing for this long has gone limp:
# a power glitch at its connector rebooted it, which clears torque and the
# goal current. Torque Enable and Goal Current live in RAM on every family.
TORQUE_LOSS_ERROR_RAD = 0.2
TORQUE_LOSS_CURRENT_MA = 5.0
TORQUE_LOSS_S = 1.0
STALL_THRESHOLD_RAD = 0.01
# Winding is over when every motor has been still this long at the same
# time: a proximal joint arriving at its stop frees slack on the distal one.
STALL_HOLD_S = 1.0
MAX_WIND_S = 30.0
# At torque: the shaft pushed this far off its anchor (the ratchet rig's
# preload threshold) while the motor is leaning on its limit.
REACH_THRESHOLD_RAD = 0.05
REACH_CURRENT_FRACTION = 0.5
# Pushed this far: well past the click, back the spool off.
OVERDRIVE_DEG = 10.0
WIGGLE_RAD = 0.08
WIGGLE_PERIOD_S = 0.2
WIGGLE_CYCLES = 3
WIGGLE_SETTLE_S = 0.5
TEMP_PERIOD_S = 1.0
# Fractions of the family's rated ceiling (the console's own thresholds):
# a motor past COOL_START holds cool until it is back under COOL_END.
COOL_START_FRACTION = 0.9
COOL_END_FRACTION = 0.7
EXTRA_PERIOD_S = 0.2

NEXT = "Next"
DONE = "Done"
START_SIDE = "Start side"
WIGGLE = "Wiggle"
SELECT_PREFIX = "select:"
WIGGLE_SIDE_PREFIX = "wiggle_side:"
SEAT_PROMPT = ("Motors holding at the hard stop — work the slack out of the "
               "bottom tendons")
ATTACH_PROMPT = "Connect the top spool and pull the top tendon snug"
TIGHTEN_PROMPT = "Screw the top spool in — the motor beeps when it is at torque"

# A hold ends with the operator's answer, or with a jump to another spool.
_JUMP = "jump"


def validate_spooling_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — spooling needs motors",
                           status_code=409)
    config = service.supervisor.config

    mode = params.get("mode", "all")
    if mode not in MODES:
        raise ServiceError(f"mode must be one of {list(MODES)}")

    joints = params.get("joints")
    if joints is None:
        joints = [j for j in config.joint_ids if j != WRIST]
    elif not isinstance(joints, list) or not joints or \
            not all(isinstance(j, str) for j in joints):
        raise ServiceError("joints must be a non-empty list of joint names, "
                           "or null for every finger joint")
    unknown = set(joints) - set(config.joint_ids)
    if unknown:
        raise ServiceError(f"unknown joints: {sorted(unknown)}")
    if WRIST in joints:
        raise ServiceError("the wrist has no spool and is not tendon driven")
    joints = list(dict.fromkeys(joints))

    raw = params.get("tighten_current_ma", TIGHTEN_CURRENT_CEILING_MA)
    try:
        tighten = float(raw)
    except (TypeError, ValueError):
        raise ServiceError("tighten_current_ma must be a number")
    if not math.isfinite(tighten) or \
            not MIN_TIGHTEN_CURRENT_MA <= tighten <= TIGHTEN_CURRENT_CEILING_MA:
        raise ServiceError(
            f"tighten_current_ma must be between {MIN_TIGHTEN_CURRENT_MA:g} "
            f"and {TIGHTEN_CURRENT_CEILING_MA:g} mA")
    # The packaged configs say ``max_current: default``; the connected hand
    # carries the family's resolved number.
    try:
        operating = float(hand_ops.resolve_family_currents(
            getattr(session.hand, "config", config)).max_current)
    except Exception as e:
        raise ServiceError(f"cannot resolve the hand's current limits: {e}",
                           status_code=503)
    ceiling = hand_ops.motor_current_ceiling_ma(session.hand) \
        or 2.0 * operating
    raw = params.get("wind_current_ma", min(DEFAULT_WIND_CURRENT_MA, operating))
    try:
        wind = float(raw)
    except (TypeError, ValueError):
        raise ServiceError("wind_current_ma must be a number")
    if not math.isfinite(wind) or not MIN_WIND_CURRENT_MA <= wind <= ceiling:
        raise ServiceError(
            f"wind_current_ma must be between {MIN_WIND_CURRENT_MA:g} and "
            f"{ceiling:g} mA (this motor family's ceiling)")
    return {"mode": mode, "joints": joints, "tighten_current_ma": tighten,
            "wind_current_ma": wind}


def motor_sides(config) -> list[dict]:
    """The pack's two sides: finger motors by ID, lower half and upper half.
    The wrist motor sits apart and is never spooled."""
    wrist = config.joint_to_motor_map.get(WRIST)
    ids = sorted(m for m in config.motor_ids if m != wrist)
    if len(ids) < 2:
        return [{"id": "A", "label": "all motors", "motor_ids": ids}]
    half = len(ids) // 2
    return [
        {"id": "A", "label": f"motors {ids[0]}–{ids[half - 1]}",
         "motor_ids": ids[:half]},
        {"id": "B", "label": f"motors {ids[half]}–{ids[-1]}",
         "motor_ids": ids[half:]},
    ]


@dataclass
class _Spool:
    joint: str
    motor_id: int
    side: str | None
    state: str = "pending"
    limit_ma: float = 0.0
    current_ma: float = 0.0
    pushed_deg: float = 0.0
    temp_c: float | None = None
    done: bool = False
    cooling: bool = False
    torque_drops: int = 0
    limp_since: float | None = None
    anchor: float | None = None
    goal: float | None = None
    last_pos: float | None = None
    prev_pos: float | None = None
    quiet_since: float | None = None

    def as_dict(self) -> dict:
        return {
            "joint": self.joint,
            "id": self.motor_id,
            "side": self.side,
            "state": self.state,
            "current_ma": round(self.current_ma, 1),
            "limit_ma": self.limit_ma,
            "pushed_deg": round(self.pushed_deg, 1),
            "temp_c": self.temp_c,
            "done": self.done,
            "cooling": self.cooling,
            "torque_drops": self.torque_drops,
        }


class SpoolingRun:
    """The lease-free body: drives one connected motor-only hand.

    Answers to the hold prompts arrive on the caller thread through
    :meth:`advance`; the tick loop picks them up between bus commands.
    """

    def __init__(self, hand, ctx: OpContext, mode: str, joints: list[str],
                 tighten_current_ma: float,
                 wind_current_ma: float | None = None):
        self.hand = hand
        self.ctx = ctx
        self.mode = mode
        self.tighten_current_ma = min(float(tighten_current_ma),
                                      TIGHTEN_CURRENT_CEILING_MA)
        config = hand_ops.resolve_family_currents(hand.config)
        self.sides = motor_sides(config)
        side_of = {m: side["id"] for side in self.sides
                   for m in side["motor_ids"]}
        side_rank = {side["id"]: i for i, side in enumerate(self.sides)}
        spools = [
            _Spool(joint=j, motor_id=config.joint_to_motor_map[j],
                   side=side_of.get(config.joint_to_motor_map[j]))
            for j in joints
        ]
        # Side by side, in ID order along each side: the order the spools sit
        # in the pack, which is the order a hand with a ratchet works in.
        self.spools = sorted(
            spools, key=lambda s: (side_rank.get(s.side, len(side_rank)),
                                   s.motor_id))
        # Every pull and hold short of the torque wrench runs at the winding
        # current: it is the most a half-built hand's connectors can take.
        self.wind_current_ma = float(wind_current_ma) \
            if wind_current_ma is not None \
            else min(DEFAULT_WIND_CURRENT_MA, float(config.max_current))
        self.hold_current_ma = self.wind_current_ma
        self._profiles: dict = {}
        self._read_failures = 0
        self.max_temp_c = hand_ops.max_motor_temp_c(hand)
        self._phase = "pending"
        self._phase_limit_ma = self.hold_current_ma
        self._active: _Spool | None = None
        self._jump: _Spool | None = None
        self._group: list[_Spool] = []
        self._written_limits: dict[int, float] = {}
        self._lock = threading.Lock()
        self._options: list[str] = []
        self._answer: str | None = None
        self._selected: str | None = None
        self._wiggle_requested: list[int] | None = None
        self._wiggle_ids: list[int] = []
        self._wiggle_plan: list[tuple[float, float]] = []
        self._wiggle_settle_until = 0.0
        self._temp_at = 0.0
        self._extra_at = 0.0

    # ----- caller-thread input ------------------------------------------------------

    def advance(self, value: str) -> bool:
        """Consume an answer while a hold is open. Returns False outside a
        hold so the manager reports 409 instead of swallowing it."""
        with self._lock:
            if not self._options:
                return False
            if value in self._options:
                self._answer = value
            elif value == WIGGLE:
                self._wiggle_requested = (
                    [self._active.motor_id] if self._active else [])
            elif value.startswith(WIGGLE_SIDE_PREFIX):
                wanted = value[len(WIGGLE_SIDE_PREFIX):]
                self._wiggle_requested = [
                    s.motor_id for s in self.spools if s.side == wanted]
            elif value.startswith(SELECT_PREFIX):
                self._selected = value[len(SELECT_PREFIX):]
            else:
                self.ctx.log(f"ignored input {value!r} (expected "
                             f"{self._options})")
            return True

    # ----- run ----------------------------------------------------------------------

    def run(self) -> dict:
        ctx, hand = self.ctx, self.hand
        ctx.check_stop()
        ctx.log(f"spooling {len(self.spools)} motor(s), "
                f"{self.mode.replace('_', ' ')}: "
                + ", ".join(f"{s.joint} (M{s.motor_id})" for s in self.spools))
        hand_ops.enter_current_based_position(hand)
        try:
            self._profiles = hand_ops.read_servo_profiles(hand)
            hand_ops.set_velocity_profile(
                hand, [s.motor_id for s in self.spools],
                WIND_VELOCITY_RAD_S, WIND_ACCELERATION_RAD_S2)
            if self.mode == "all":
                self._run_all()
            else:
                self._run_one_by_one()
        finally:
            self._close_hold()
            try:
                hand_ops.restore_servo_profiles(hand, self._profiles)
            except Exception:
                logger.exception("servo profile restore failed")
            try:
                hand_ops.restore_after_hold(hand)
            except Exception as e:
                logger.exception("spooling release failed")
                ctx.log(f"RELEASE FAILED — check the hand by hand: {e}")
            else:
                ctx.log("hold released — torque off, control mode restored")
            self._active = None
            self._set_phase("released",
                            detail="torque off, control mode restored")
        return {
            "mode": self.mode,
            "joints": [s.joint for s in self.spools],
            "reached": [s.joint for s in self.spools
                        if s.state in ("reached", "over")],
            "released": True,
        }

    def _run_all(self) -> None:
        """Side by side, the way the pack is assembled: wind and seat one
        side's motors together, take its top spools one at a time, then the
        other side. A finished side keeps holding at the tightening limit."""
        groups = [[s for s in self.spools if s.side == side["id"]]
                  for side in self.sides]
        groups = [g for g in groups if g]
        for index, group in enumerate(groups):
            side = group[0].side or ""
            label = f"side {side}"
            if index > 0:
                # Nothing moves on the next side until asked: the operator's
                # hands are still on the one just finished.
                self._active = None
                self._set_phase("side_done", detail=f"side "
                                f"{groups[index - 1][0].side} finished — "
                                f"start side {side} when ready")
                self.ctx.log(f"side {groups[index - 1][0].side} finished; "
                             f"waiting to start side {side}")
                self._hold([], f"Side {groups[index - 1][0].side} is done — "
                           f"start side {side}? Its motors will move.",
                           [f"{START_SIDE} {side}"], lead=False)
            self._wind(group, label)
            self._seat(group, label)
            last_side = index == len(groups) - 1
            self._queue_top_spools(group, side, last_side)
        self._active = None

    def _queue_top_spools(self, group: list[_Spool], side: str,
                          last_side: bool) -> None:
        self._group = group
        spool = self._next_to_work(None, group)
        while spool is not None:
            self._set_active(spool)
            done = sum(s.done for s in group)
            label = f"{spool.joint} (side {side} {done + 1}/{len(group)})"
            if self._attach([spool], label, queue=True) == _JUMP:
                spool = self._take_jump()
                continue
            last = last_side and done == len(group) - 1
            answer = self._tighten([spool], [DONE] if last else [NEXT],
                                   label=label, queue=True)
            if answer == _JUMP:
                # Left before it clicked: back to the full hold, not done.
                spool.limit_ma = self.hold_current_ma
                spool.state = "holding"
                self._apply_limits()
                spool = self._take_jump()
                continue
            spool.done = True
            spool = self._next_to_work(spool, group)

    def _run_one_by_one(self) -> None:
        total = len(self.spools)
        for index in range(total):
            spool = self._next_pending()
            self._set_active(spool)
            label = f"{spool.joint} ({index + 1}/{total})"
            self._wind([spool], label)
            self._seat([spool], label)
            self._attach([spool], label)
            last = index == total - 1
            self._tighten([spool], [DONE] if last else [NEXT], label=label)
            spool.done = True
        self._active = None

    def _done_count(self) -> int:
        return sum(s.done for s in self.spools)

    def _next_to_work(self, after: _Spool | None,
                      group: list[_Spool]) -> _Spool | None:
        """The next unfinished spool along the side after ``after``,
        wrapping round — so a tile click sets where the queue starts."""
        start = group.index(after) + 1 if after is not None else 0
        for offset in range(len(group)):
            spool = group[(start + offset) % len(group)]
            if not spool.done:
                return spool
        return None

    def _next_pending(self) -> _Spool:
        pending = [s for s in self.spools if not s.done]
        with self._lock:
            wanted, self._selected = self._selected, None
        for spool in pending:
            if spool.joint == wanted:
                return spool
        return pending[0]

    def _take_jump(self) -> _Spool:
        spool = self._jump
        self._jump = None
        return spool

    # ----- phases -------------------------------------------------------------------

    def _wind(self, driven: list[_Spool], label: str = "") -> None:
        ctx = self.ctx
        prefix = f"{label}: " if label else ""
        self._phase_limit_ma = self.wind_current_ma
        for spool in driven:
            spool.limit_ma = self.wind_current_ma
            spool.state = "winding"
            spool.quiet_since = None
            spool.goal = None
        self._apply_limits()
        self._set_phase("winding", progress=0.0,
                        detail=prefix + "driving to the hard stop")
        ctx.log(f"{prefix}winding to the hard stop at "
                f"{self.wind_current_ma:.0f} mA")
        failed = hand_ops.enable_torque(self.hand,
                                        [s.motor_id for s in driven])
        if failed:
            raise RuntimeError(f"torque enable not acknowledged by motors "
                               f"{failed} — refusing to drive the rest")

        started = time.monotonic()
        while True:
            now = time.monotonic()
            if self._sample(now):
                targets: dict[int, float] = {}
                for spool in driven:
                    pos = spool.last_pos
                    prev = spool.prev_pos
                    moved = prev is None or \
                        abs(pos - prev) >= STALL_THRESHOLD_RAD
                    if moved:
                        spool.quiet_since = None
                        if spool.state == "stalled":
                            spool.state = "winding"
                    else:
                        spool.quiet_since = spool.quiet_since or now
                        if spool.state == "winding" and \
                                now - spool.quiet_since >= STALL_HOLD_S:
                            spool.state = "stalled"
                            ctx.log(f"{spool.joint}: at the hard stop")
                    if spool.state != "pending" and not spool.cooling:
                        targets[spool.motor_id] = self._pull_goal(spool)
                    self._watch_torque(spool, spool.goal, now)
                hand_ops.write_motor_targets(self.hand, targets)

            stalled = sum(s.state == "stalled" for s in driven)
            self._publish(progress=stalled / max(len(driven), 1))
            if stalled == len(driven):
                break
            if now - started >= MAX_WIND_S:
                for spool in driven:
                    if spool.state == "winding":
                        spool.state = "stalled"
                        ctx.log(f"{spool.joint}: still moving after "
                                f"{MAX_WIND_S:.0f} s — holding where it is")
                break
            ctx.sleep(TICK_S)
        for spool in driven:
            spool.anchor = spool.last_pos
        self._publish(progress=1.0, force=True)

    def _seat(self, driven: list[_Spool], label: str = "") -> None:
        prefix = f"{label}: " if label else ""
        self._phase_limit_ma = self.wind_current_ma
        for spool in driven:
            spool.limit_ma = self.wind_current_ma
            spool.state = "holding"
        self._apply_limits()
        self._set_phase("seating", detail=prefix + "motors pulling at "
                        f"{self.wind_current_ma:.0f} mA — wiggle the slack out")
        self.ctx.log(f"{prefix}pulling at {self.wind_current_ma:.0f} mA; "
                     "wiggle the slack out of the bottom tendons, then Next")
        self._hold(driven, SEAT_PROMPT, [NEXT], lead=True)
        for spool in driven:
            spool.anchor = spool.last_pos

    def _attach(self, driven: list[_Spool], label: str = "",
                queue: bool = False) -> str:
        prefix = f"{label}: " if label else ""
        self._phase_limit_ma = self.hold_current_ma
        for spool in driven:
            spool.limit_ma = self.hold_current_ma
            spool.state = "holding"
        self._apply_limits()
        self._set_phase("attaching", detail=prefix + "motor holding firm — "
                        "connect the top spool")
        self.ctx.log(f"{prefix}holding the anchor; connect the top spool and "
                     "pull the top tendon snug")
        hand_ops.write_motor_targets(self.hand, self._anchor_targets(driven))
        return self._hold(driven, ATTACH_PROMPT, [NEXT], lead=False,
                          queue=queue)

    def _tighten(self, driven: list[_Spool], options: list[str], *,
                 label: str = "", queue: bool = False) -> str:
        prefix = f"{label}: " if label else ""
        self._phase_limit_ma = self.tighten_current_ma
        for spool in driven:
            spool.limit_ma = self.tighten_current_ma
            spool.state = "holding"
            spool.pushed_deg = 0.0
        self._apply_limits()
        self._set_phase("tightening", detail=prefix + "torque wrench at "
                        f"{self.tighten_current_ma:.0f} mA — screw the top "
                        "spool in")
        self.ctx.log(f"{prefix}current limit {self.tighten_current_ma:.0f} mA: "
                     "screw the top spool in until the motor gives way")
        hand_ops.write_motor_targets(self.hand, self._anchor_targets(driven))
        return self._hold(driven, TIGHTEN_PROMPT, options, lead=False,
                          tighten=True, queue=queue)

    # ----- hold loop ----------------------------------------------------------------

    def _hold(self, driven: list[_Spool], prompt: str, options: list[str], *,
              lead: bool, tighten: bool = False, queue: bool = False) -> str:
        """Park in ``awaiting_input`` while the tick loop keeps the motors
        where the phase wants them. Returns the answer, or ``_JUMP`` when
        a tile click moved the queue to another spool."""
        ctx = self.ctx
        with self._lock:
            self._options = list(options)
            self._answer = None
            self._selected = None
            self._wiggle_requested = None
        ctx.announce_input(prompt, options)
        try:
            while True:
                with self._lock:
                    answer = self._answer
                    selected, self._selected = self._selected, None
                    wiggle, self._wiggle_requested = \
                        self._wiggle_requested, None
                if answer is not None:
                    ctx.log(f"{self._phase}: {answer}")
                    return answer
                now = time.monotonic()
                if queue and selected is not None:
                    target = self._spool_named(selected)
                    if target is None or target is self._active or target.done:
                        pass
                    elif target not in self._group:
                        ctx.log(f"{target.joint} is on the other side — it "
                                "comes up once this side is finished")
                    else:
                        self._jump = target
                        ctx.log(f"{self._phase}: jumping to {target.joint}")
                        return _JUMP
                if wiggle is not None:
                    self._start_wiggle(now, wiggle)
                if self._sample(now):
                    targets: dict[int, float] = {}
                    if lead:
                        for spool in driven:
                            if not spool.cooling:
                                targets[spool.motor_id] = self._pull_goal(spool)
                            self._watch_torque(spool, spool.goal, now)
                    else:
                        for spool in self.spools:
                            if spool.anchor is not None and \
                                    spool.last_pos is not None:
                                spool.pushed_deg = math.degrees(
                                    spool.last_pos - spool.anchor)
                        if tighten:
                            for spool in driven:
                                self._judge_torque(spool, now)
                        for spool in self.spools:
                            if spool.state != "pending":
                                self._watch_torque(spool, spool.anchor, now)
                    targets.update(self._wiggle_targets(now))
                    hand_ops.write_motor_targets(self.hand, targets)
                self._publish()
                ctx.sleep(TICK_S)
        finally:
            self._close_hold()

    def _judge_torque(self, spool: _Spool, now: float) -> None:
        if spool.motor_id in self._wiggle_ids and \
                now < self._wiggle_settle_until:
            return
        pushed = abs(math.radians(spool.pushed_deg))
        if spool.state == "holding" and pushed >= REACH_THRESHOLD_RAD and \
                spool.current_ma >= REACH_CURRENT_FRACTION * spool.limit_ma:
            spool.state = "reached"
            self.ctx.log(f"{spool.joint}: at torque — gave way after "
                         f"{abs(spool.pushed_deg):.1f}° at "
                         f"{spool.current_ma:.0f} mA")
        if spool.state == "reached" and abs(spool.pushed_deg) > OVERDRIVE_DEG:
            spool.state = "over"
            self.ctx.log(f"{spool.joint}: pushed {abs(spool.pushed_deg):.0f}° "
                         "off the hard stop — past the click, back it off")
        elif spool.state == "over" and abs(spool.pushed_deg) <= OVERDRIVE_DEG:
            spool.state = "reached"

    def _close_hold(self) -> None:
        with self._lock:
            was_open = bool(self._options)
            self._options = []
            self._answer = None
        self._wiggle_plan = []
        if was_open:
            self.ctx.resume_running()

    # ----- the active spool and the wiggle --------------------------------------------

    def _spool_named(self, joint: str) -> _Spool | None:
        for spool in self.spools:
            if spool.joint == joint:
                return spool
        return None

    def _set_active(self, spool: _Spool | None) -> None:
        if spool is self._active:
            return
        self._active = spool
        if spool is not None:
            self.ctx.log(f"next spool: {spool.joint} (motor {spool.motor_id})")
            if spool.anchor is not None:
                self._start_wiggle(time.monotonic(), [spool.motor_id])
        self._publish(force=True)

    def _start_wiggle(self, now: float, motor_ids: list[int]) -> None:
        # Off the stop and back: the only free direction at a hard stop.
        ids = [s.motor_id for s in self.spools
               if s.motor_id in motor_ids and s.anchor is not None
               and s.state != "pending"]
        if not ids:
            return
        plan = []
        for cycle in range(WIGGLE_CYCLES):
            base = now + cycle * 2 * WIGGLE_PERIOD_S
            plan.append((-WIGGLE_RAD, base + WIGGLE_PERIOD_S))
            plan.append((0.0, base + 2 * WIGGLE_PERIOD_S))
        self._wiggle_ids = ids
        self._wiggle_plan = plan
        self._wiggle_settle_until = plan[-1][1] + WIGGLE_SETTLE_S

    def _wiggle_targets(self, now: float) -> dict[int, float]:
        while self._wiggle_plan and self._wiggle_plan[0][1] <= now:
            self._wiggle_plan.pop(0)
        if not self._wiggle_plan:
            return {}
        offset = self._wiggle_plan[0][0]
        return {s.motor_id: s.anchor + offset for s in self.spools
                if s.motor_id in self._wiggle_ids and s.anchor is not None}

    def _watch_torque(self, spool: _Spool, reference: float | None,
                      now: float) -> None:
        """Re-arm a motor that went limp: far from where it is held yet
        drawing nothing. Limits go back first — a rebooted servo wakes up
        with its EEPROM ceiling as goal current, not ours."""
        if reference is None or spool.last_pos is None or spool.cooling:
            spool.limp_since = None
            return
        limp = abs(reference - spool.last_pos) > TORQUE_LOSS_ERROR_RAD and \
            spool.current_ma < TORQUE_LOSS_CURRENT_MA
        if not limp:
            spool.limp_since = None
            return
        spool.limp_since = spool.limp_since or now
        if now - spool.limp_since < TORQUE_LOSS_S:
            return
        spool.limp_since = None
        spool.torque_drops += 1
        self.ctx.log(f"{spool.joint}: went limp under load — the servo lost "
                     "torque (a power glitch at its connector reboots it); "
                     f"re-arming with its limits ({spool.torque_drops}×)")
        self._written_limits = {}
        self._apply_limits()
        try:
            hand_ops.set_velocity_profile(
                self.hand, [spool.motor_id],
                WIND_VELOCITY_RAD_S, WIND_ACCELERATION_RAD_S2)
        except Exception as e:
            logger.warning("profile re-apply failed on %s: %s", spool.joint, e)
        failed = hand_ops.enable_torque(self.hand, [spool.motor_id])
        if failed:
            self.ctx.log(f"{spool.joint}: torque enable not acknowledged — "
                         "check its connector")
        self._publish(force=True)

    def _pull_goal(self, spool: _Spool) -> float:
        """The goal kept ahead of the shaft; it only ever advances."""
        ahead = spool.last_pos + WIND_LEAD_RAD
        spool.goal = ahead if spool.goal is None else max(spool.goal, ahead)
        return spool.goal

    # ----- sampling, thermal guard ----------------------------------------------------

    def _sample(self, now: float) -> bool:
        """Read the bus into the spools; False when the read was stale.
        A bus that stays silent ends the run rather than holding blind."""
        try:
            read = hand_ops.read_motor_state(self.hand)
        except Exception as e:
            logger.warning("motor read failed: %s", e)
            read = None
        if read is None:
            self._read_failures += 1
            if self._read_failures >= MAX_READ_FAILURES:
                raise RuntimeError(
                    f"no valid motor read for {MAX_READ_FAILURES} ticks — "
                    "check the motor bus")
            return False
        self._read_failures = 0
        positions, currents = read
        for spool in self.spools:
            spool.prev_pos = spool.last_pos
            spool.last_pos = positions[spool.motor_id]
            spool.current_ma = abs(currents[spool.motor_id])
        if now - self._temp_at >= TEMP_PERIOD_S:
            self._temp_at = now
            self._update_thermal()
        return True

    def _update_thermal(self) -> None:
        try:
            temps = hand_ops.read_motor_temps(self.hand)
        except Exception as e:
            logger.debug("temperature read failed: %s", e)
            return
        for spool in self.spools:
            spool.temp_c = temps.get(spool.motor_id)
        if self.max_temp_c is None:
            return
        changed = False
        for spool in self.spools:
            if spool.temp_c is None or spool.state == "pending":
                continue
            if not spool.cooling and \
                    spool.temp_c >= COOL_START_FRACTION * self.max_temp_c:
                spool.cooling = True
                changed = True
                self.ctx.log(f"{spool.joint}: {spool.temp_c:.0f} °C — holding "
                             "cool until it is back under "
                             f"{COOL_END_FRACTION * self.max_temp_c:.0f} °C")
                if spool.last_pos is not None:
                    hand_ops.write_motor_targets(
                        self.hand, {spool.motor_id: spool.last_pos})
            elif spool.cooling and \
                    spool.temp_c <= COOL_END_FRACTION * self.max_temp_c:
                spool.cooling = False
                changed = True
                self.ctx.log(f"{spool.joint}: cooled to {spool.temp_c:.0f} °C "
                             "— back at full hold")
        if changed:
            self._apply_limits()

    def _apply_limits(self) -> None:
        wanted = {
            s.motor_id: (self.tighten_current_ma if s.cooling else s.limit_ma)
            for s in self.spools if s.state != "pending"
        }
        if wanted != self._written_limits:
            hand_ops.set_current_limits(self.hand, wanted)
            self._written_limits = wanted

    # ----- plumbing -----------------------------------------------------------------

    def _anchor_targets(self, spools: list[_Spool]) -> dict[int, float]:
        return {s.motor_id: s.anchor for s in spools if s.anchor is not None}

    def _set_phase(self, phase: str, detail: str | None = None,
                   progress: float | None = None) -> None:
        self._phase = phase
        self.ctx.set_phase(phase, detail=detail, progress=progress)
        self._publish(force=True)

    def extra(self) -> dict:
        return {
            "mode": self.mode,
            "phase": self._phase,
            "tighten_current_ma": self.tighten_current_ma,
            "wind_current_ma": self.wind_current_ma,
            "limit_ma": self._phase_limit_ma,
            "max_temp_c": self.max_temp_c,
            "active": self._active.joint if self._active else None,
            "sides": [dict(side) for side in self.sides],
            "motors": [s.as_dict() for s in self.spools],
        }

    def _publish(self, progress: float | None = None,
                 force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._extra_at < EXTRA_PERIOD_S:
            return
        self._extra_at = now
        if progress is not None:
            self.ctx.set_progress(progress)
        self.ctx.set_extra(self.extra())


class SpoolingOperation(Operation):
    kind = "spooling"

    def __init__(self, params: dict):
        super().__init__(params)
        self._run: SpoolingRun | None = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_spooling_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config.config_path, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None)
            self._run = SpoolingRun(hand, ctx, **self.params)
            return self._run.run()
        finally:
            self._run = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()

    def handle_input(self, value: str) -> bool:
        run = self._run
        return run is not None and run.advance(value)


# ----- mock mode ------------------------------------------------------------------


class _SimClient:
    max_operating_temp_c = 70.0
    max_current_ma = 910.0


class SimulatedSpoolHand:
    """In-memory motor-only hand for the real :class:`SpoolingRun` loop.

    Torque-enabled motors travel toward their goal and stop at a hard stop.
    A motor whose limit is lowered to the torque-wrench ceiling gets "screwed
    in": its current climbs to the limit over ``ramp_s`` and the shaft is then
    pushed just past the click, so the tightening grid can be watched without
    hardware. Motors warm while they lean on their limit.
    """

    TRAVEL_RAD_PER_READ = 0.1
    HARD_STOP_RAD = 0.6
    HEAT_C_PER_READ = 0.02
    COOL_C_PER_READ = 0.05
    # How far a simulated screw pushes the shaft: just past the click.
    PUSH_RAD = 0.08

    def __init__(self, config, ramp_s: float = 3.0):
        self.config = config
        self.ramp_s = ramp_s
        self.last_read_ok = True
        self.control_mode = config.control_mode
        self.motor_client = _SimClient()
        self.torque: list[int] = []
        self.temps = {m: 35.0 for m in config.motor_ids}
        self._pos = {m: 0.0 for m in config.motor_ids}
        self._goal = dict(self._pos)
        self._limit = {m: float(config.max_current) for m in config.motor_ids}
        self._screw_started: dict[int, float] = {}
        self._pushed: dict[int, float] = {}

    def set_control_mode(self, mode, motor_ids=None) -> None:
        self.control_mode = mode

    def get_servo_profile(self) -> dict:
        return {m: None for m in self.config.motor_ids}

    def set_servo_profile(self, profiles: dict) -> None:
        self.profiles = dict(profiles)

    def set_max_current(self, current) -> None:
        if isinstance(current, (list, tuple)):
            self._limit = {m: float(c)
                           for m, c in zip(self.config.motor_ids, current)}
        else:
            self._limit = {m: float(current) for m in self.config.motor_ids}
        now = time.monotonic()
        queued = [m for m in self.torque
                  if self._limit[m] <= TIGHTEN_CURRENT_CEILING_MA
                  and m not in self._screw_started]
        for index, m in enumerate(queued):
            self._screw_started[m] = now + index * self.ramp_s * 1.5

    def enable_torque(self, motor_ids=None) -> list[int]:
        for m in (motor_ids or self.config.motor_ids):
            if m not in self.torque:
                self.torque.append(m)
        return []

    def disable_torque(self, motor_ids=None) -> list[int]:
        self.torque = [m for m in self.torque
                       if motor_ids is not None and m not in motor_ids]
        return []

    def write_motor_pos(self, motor_ids, positions) -> None:
        for m, p in zip(motor_ids, positions):
            self._goal[m] = float(p)

    def get_motor_temp(self, as_dict: bool = False):
        return dict(self.temps)

    def get_motor_state(self):
        import numpy as np
        from orca_core.hardware.motor_client import MotorRead

        now = time.monotonic()
        currents = []
        for m in self.config.motor_ids:
            current = 0.0
            if m in self.torque:
                limit = self._limit[m]
                screwing = self._screw_started.get(m)
                elapsed = None if screwing is None else now - screwing
                if elapsed is not None and elapsed >= 0:
                    current = limit * min(1.0, elapsed / self.ramp_s)
                    if elapsed > self.ramp_s and \
                            self._pushed.get(m, 0.0) < self.PUSH_RAD:
                        # The screw overcomes the hold: the shaft gives way.
                        self._pos[m] -= 0.02
                        self._pushed[m] = self._pushed.get(m, 0.0) + 0.02
                else:
                    delta = self._goal[m] - self._pos[m]
                    step = max(-self.TRAVEL_RAD_PER_READ,
                               min(self.TRAVEL_RAD_PER_READ, delta))
                    self._pos[m] = max(-self.HARD_STOP_RAD,
                                       min(self.HARD_STOP_RAD,
                                           self._pos[m] + step))
                    blocked = abs(self._goal[m] - self._pos[m]) > 0.02
                    current = limit * (0.95 if blocked else 0.05)
            heating = current >= 0.5 * self._limit[m]
            self.temps[m] += self.HEAT_C_PER_READ if heating \
                else -self.COOL_C_PER_READ
            self.temps[m] = max(25.0, self.temps[m])
            currents.append(current)
        ids = self.config.motor_ids
        return MotorRead(
            position=np.array([self._pos[m] for m in ids], dtype=float),
            velocity=np.zeros(len(ids)),
            current=np.array(currents, dtype=float),
        )


class SimulatedSpoolingOperation(Operation):
    """Mock-mode stand-in: the real run loop over a simulated hand, under
    the real maintenance lease."""

    kind = "spooling"

    DEFAULT_RAMP_S = 3.0

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        clean = validate_spooling_params(service, params)
        try:
            ramp = float(params.get("ramp_s", cls.DEFAULT_RAMP_S))
        except (TypeError, ValueError):
            ramp = cls.DEFAULT_RAMP_S
        clean["ramp_s"] = min(max(ramp, 0.05), 10.0)
        return clean

    def __init__(self, params: dict):
        super().__init__(params)
        self._run: SpoolingRun | None = None

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = SimulatedSpoolHand(
                hand_ops.resolve_family_currents(supervisor.config),
                ramp_s=self.params["ramp_s"])
            params = {k: self.params[k]
                      for k in ("mode", "joints", "tighten_current_ma",
                                "wind_current_ma")}
            self._run = SpoolingRun(hand, ctx, **params)
            return self._run.run()
        finally:
            self._run = None
            supervisor.exit_maintenance()

    def handle_input(self, value: str) -> bool:
        run = self._run
        return run is not None and run.advance(value)

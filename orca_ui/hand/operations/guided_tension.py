"""Guided tensioning: centre → range check → score → tension, repeated.

orca_core's run_guided_tension drives the hardware and blocks on a prompt for
every operator step; each prompt parks the op in ``awaiting_input`` through
ctx.wait_input, so stop / e-stop unwind straight through the routine, whose
cleanup leaves the motors limp. Live spreads stream through the snapshot
``extra`` (see GuidedTensionExtra in the frontend types).
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time

from orca_core.constants import (
    CALIBRATION_GROUPS,
    DEFAULT_GUIDED_TENSION_CURRENTS,
    DYNAMIXEL,
    SUPPORTED_MOTOR_TYPES,
)

from orca_ui.hand import reference
from orca_ui.hand.faults import classify_hw_error
from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.tension import DEFAULT_TENSION_OFFSET_DEG, EXTRA_DEG

logger = logging.getLogger(__name__)

PROMPTS = {
    "pose": "Torque off — pose the hand for the next finger",
    "range_check": "Drive the highlighted joints through their full range",
    "score": "Range check scored",
    "tension": "Tension carefully with the ratchet tool — do not overtension",
}
GOTO = (
    "goto:"  # answer prefix that jumps to a range stage by key, or to score / tension
)
GOTO_SCORE = f"{GOTO}score"
GOTO_TENSION = f"{GOTO}tension"
PUBLISH_PERIOD_S = 0.1
HOLD_BOUNDS_MA = (20.0, 500.0)
# Run settings: currents in mA, and how far the motors turn counterclockwise while tensioning in degrees.
CURRENT_BOUNDS_MA = {
    "hold_ap": HOLD_BOUNDS_MA,
    "hold_mcp": HOLD_BOUNDS_MA,
    "hold_pip": HOLD_BOUNDS_MA,
    "tension_current": (50.0, 1000.0),
    "tension_offset_deg": (0.0, 45.0),
}
# Input values "current:<key>=<mA>" change a current mid-run instead of answering a prompt.
CURRENT_INPUT = "current:"
LIVE_STEP = {
    "hold_ap": "range",
    "hold_mcp": "range",
    "hold_pip": "range",
    "tension_current": "tension",
}
# Input values "pass:<group>=<value>" change a group's pass threshold mid-run
# (a fraction under fraction scoring, degrees of slack under slack scoring).
PASS_INPUT = "pass:"
# Input values "reboot:<motor id>" clear a motor's latched hardware error and hold it again.
REBOOT_INPUT = "reboot:"
# "again:<joint>": drop the joint's kept pass so the range check tests it again.
AGAIN_INPUT = "again:"
PASS_GROUPS = ("ap", "mcp", "pip")
# Which rule scores the range check (see run_guided_tension): "fraction" is
# the spread as a share of the expected travel with the best kept across
# rounds; "slack" is expected minus a settled, twice-reached spread, in degrees.
SCORING_FRACTION = "fraction"
SCORING_SLACK = "slack"
SCORINGS = (SCORING_FRACTION, SCORING_SLACK)
PASS_BOUNDS_FRACTION = (0.1, 1.0)
DEFAULT_PASS_FRACTION = 0.8
# Slack tolerance (expected travel minus the swept spread), motor degrees.
PASS_BOUNDS_DEG = (0.5, 30.0)
DEFAULT_PASS_SLACK_DEG = {"ap": 3.0, "mcp": 5.0, "pip": 5.0}


def default_currents(config=None, family: str | None = None) -> dict:
    """The run's starting currents: the hand config's guided_tension_currents for ``family``."""
    if config is None:
        entry = DEFAULT_GUIDED_TENSION_CURRENTS[
            family if family in SUPPORTED_MOTOR_TYPES else DYNAMIXEL
        ]
    else:
        entry = config.guided_tension_currents_for(family)
    hold = entry["hold"]
    return {
        "hold_ap": float(hold["abd"]),
        "hold_mcp": float(hold["mcp"]),
        "hold_pip": float(hold["pip"]),
        "tension_current": float(entry["tension"]),
        "tension_offset_deg": DEFAULT_TENSION_OFFSET_DEG,
    }


def fixed_holds(config, family: str | None = None) -> dict:
    """Joints the hand config holds at their own current instead of their group's."""
    hold = config.guided_tension_currents_for(family)["hold"]
    return {joint: ma for joint, ma in hold.items() if joint not in CALIBRATION_GROUPS}


def _unit(key: str) -> str:
    return "°" if key.endswith("_deg") else " mA"


def motor_family(service) -> str | None:
    """The connected hand's motor family, as resolved at connect."""
    session = service.session
    config = session.hand.config if session is not None else service.supervisor.config
    family = getattr(config, "motor_type", None)
    if family is None and session is not None:
        family = hand_ops.hand_family(session.hand)
    return family if family in SUPPORTED_MOTOR_TYPES else None


def joint_group(joint: str) -> str:
    """ap: abductions (and the thumb's cmc), mcp: MCPs, pip: PIPs (and the thumb's dip)."""
    if joint.endswith("_abd") or joint == "thumb_cmc":
        return "ap"
    return "mcp" if joint.endswith("_mcp") else "pip"


def validate_guided_tension_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — tensioning needs motors", status_code=409)
    if not hand_ops.guided_tension_supported():
        raise ServiceError(
            "the installed orca_core has no guided tensioning", status_code=409
        )
    clean = {}
    for key, (low, high) in CURRENT_BOUNDS_MA.items():
        if params.get(key) is None:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            raise ServiceError(f"{key} must be a number", status_code=422)
        if not low <= value <= high:
            raise ServiceError(
                f"{key} must be between {low:.0f} and {high:.0f}{_unit(key)}",
                status_code=422,
            )
        clean[key] = value
    scoring = params.get("scoring") or SCORING_FRACTION
    if scoring not in SCORINGS:
        raise ServiceError(f"scoring must be one of {', '.join(SCORINGS)}", status_code=422)
    clean["scoring"] = scoring
    for key, (low, high), unit in (
        ("pass_fractions", PASS_BOUNDS_FRACTION, "a fraction"),
        ("pass_slack_deg", PASS_BOUNDS_DEG, "degrees"),
    ):
        passes = params.get(key) or {}
        if not isinstance(passes, dict) or not set(passes) <= set(PASS_GROUPS):
            raise ServiceError(
                f"{key} must map {', '.join(PASS_GROUPS)} to {unit}", status_code=422
            )
        for group, value in passes.items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ServiceError(f"{key}.{group} must be a number", status_code=422)
            if not low <= value <= high:
                raise ServiceError(
                    f"{key}.{group} must be between {low:g} and {high:g}", status_code=422
                )
            clean.setdefault(key, {})[group] = value
    clean["resume"] = bool(params.get("resume", True))
    clean["any_hardware"] = bool(params.get("any_hardware", False))
    config = service.supervisor.config
    start_at = params.get("start_at")
    if start_at not in (None, "tension"):
        raise ServiceError("start_at must be 'tension' or omitted", status_code=422)
    if start_at is not None:
        clean["start_at"] = start_at
    # Tendons to ratchet from the sweep after calibration: per joint its
    # friction as a percentage of the reference and the clicks the sweep counted.
    ratchet = params.get("ratchet_joints")
    if ratchet is not None:
        known = set(config.joint_ids) - {"wrist"}
        if not isinstance(ratchet, dict) or not set(ratchet) <= known or not all(
            isinstance(v, dict) for v in ratchet.values()
        ):
            raise ServiceError(
                "ratchet_joints must map this hand's finger joints to {pct, clicks}", status_code=422
            )
        try:
            clean["ratchet_joints"] = {
                j: {
                    "pct": None if v.get("pct") is None else float(v["pct"]),
                    "clicks": None if v.get("clicks") is None else int(v["clicks"]),
                }
                for j, v in ratchet.items()
            }
        except (TypeError, ValueError):
            raise ServiceError("ratchet_joints values must be numbers", status_code=422)
    if not (getattr(config, "uses_motor_travel", True) or clean["any_hardware"]):
        raise ServiceError(
            "guided tensioning needs v2.1 hardware — use the hold dialog, or "
            "force guided in the tension settings",
            status_code=409,
        )
    clean["defaults"] = default_currents(
        service.supervisor.config, motor_family(service)
    )
    return clean


class _Presenter:
    """Turns the routine's prompts and progress events into snapshot updates."""

    def __init__(self, ctx: OpContext, currents: dict, on_prompt=None, start_at: str | None = None):
        self._ctx = ctx
        self._on_prompt = on_prompt
        # "tension": the first pose prompt is answered with goto:tension by itself.
        self._start_at = start_at
        self._extra: dict = {
            "step": "pose",
            "round": 1,
            "motors": [],
            "history": [],
            "stages": hand_ops.range_stages(),
            "scoring": SCORING_FRACTION,
            **currents,
        }
        self._slack = self._extra["scoring"] == SCORING_SLACK
        self._lock = threading.Lock()
        self._last_publish = 0.0

    @property
    def step(self) -> str:
        return self._extra["step"]

    def set_currents(self, currents: dict) -> None:
        with self._lock:
            self._extra.update(currents)
            self._publish()

    def _publish(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < PUBLISH_PERIOD_S:
            return
        self._last_publish = now
        self._ctx.set_extra(dict(self._extra))

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "step":
                if event["round"] != self._extra["round"]:
                    self._extra.update(motors=[], passed=0, scored=0, fraction=0.0)
                self._extra.update(step=event["step"], round=event["round"])
                if "stage" in event:
                    self._extra.update(
                        {k: event[k] for k in ("stage", "stage_index", "stage_count")}
                    )
                if "absent_joints" in event:
                    absent = set(event["absent_joints"])
                    self._extra["absent_joints"] = sorted(absent)
                    # The routine drops a stage with no present joint; the sidebar does too.
                    self._extra["stages"] = [
                        st
                        for st in hand_ops.range_stages()
                        if any(j not in absent for j in st["joints"])
                    ]
                self._publish()
            elif kind in ("spread", "score"):
                self._extra.update(
                    {k: event[k] for k in ("passed", "scored", "fraction")}
                )
                self._extra["motors"] = [self._with_clicks(m) for m in event["motors"]]
                if "excluded" in event:
                    self._extra["excluded"] = list(event["excluded"])
                if kind == "score":
                    self._extra["history"] = self._extra["history"] + [
                        {k: event[k] for k in ("round", "passed", "scored", "fraction")}
                    ]
                    self._ctx.log(
                        f"round {event['round']}: {event['passed']}/{event['scored']} "
                        + ("joints within their slack tolerance" if self._slack
                           else "motors reached their travel")
                    )
                self._publish(force=kind == "score")
            elif kind == "pulled":
                self._extra["pulled_deg"] = event["total_deg"]
                self._publish()
            elif kind == "fault":
                self._set_fault(event["motor"], event.get("joint"), event["flags"])
                self._ctx.log(
                    f"motor {event['motor']} ({event.get('joint')}) has latched "
                    f"{' + '.join(event['flags'])} and is not holding — reboot it to continue"
                )
                self._publish()
            elif kind == "fault_cleared":
                faults = dict(self._extra.get("faults") or {})
                faults.pop(str(event["motor"]), None)
                self._extra["faults"] = faults
                self._ctx.log(f"motor {event['motor']} cleared and holding again")
                self._publish()
            elif kind == "resumed":
                if "best" in event:
                    best = event["best"]
                    self._extra["resumed"] = {
                        "rounds": event["rounds"],
                        "updated_at": event.get("updated_at"),
                        "joints": len(best),
                    }
                    self._ctx.log(
                        f"resumed saved progress: {len(best)} joints scored "
                        f"over {event['rounds']} earlier round(s)"
                    )
                else:
                    scores = event.get("scores") or {}
                    self._extra["resumed"] = {
                        "rounds": event["rounds"],
                        "updated_at": event.get("updated_at"),
                        "joints": len(scores),
                        "passed": sum(v.get("status") == "pass" for v in scores.values()),
                    }
                    self._ctx.log(
                        f"continuing after {event['rounds']} earlier round(s); every joint "
                        f"is checked again"
                    )
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def _with_clicks(self, motor: dict) -> dict:
        """Add the ratchet clicks the joint's slack still needs: its slack in
        degrees, or the travel it is short of (expected × (1 − fraction))."""
        slack = motor.get("slack_deg")
        if slack is None and motor.get("fraction") is not None and motor.get("expected_deg"):
            slack = motor["expected_deg"] * max(0.0, 1.0 - motor["fraction"])
        return {**motor, "clicks_left": reference.clicks_for_slack(slack, motor["joint"])}

    def _set_fault(self, motor: int, joint, flags: list, relatched: bool = False) -> None:
        info = classify_hw_error(flags, motor=motor, joint=joint)
        faults = dict(self._extra.get("faults") or {})
        faults[str(motor)] = {**info, "motor": int(motor), "joint": joint, "relatched": relatched}
        self._extra["faults"] = faults

    def relatched(self, motor: int, joint, flags: list) -> None:
        with self._lock:
            self._set_fault(motor, joint, flags, relatched=True)
            self._publish()

    def prompt(self, prompt: dict) -> str:
        action = prompt["action"]
        with self._lock:
            self._publish()
        self._ctx.set_phase(action, detail=f"round {prompt.get('round', 1)}")
        if self._on_prompt is not None:
            self._on_prompt()
        if self._start_at == "tension" and action == "pose" and GOTO_TENSION in prompt["options"]:
            self._start_at = None
            self._ctx.log("opened with a ratchet list: straight to the ratchet")
            return GOTO_TENSION
        self._start_at = None
        return self._ctx.wait_input(PROMPTS[action], list(prompt["options"]))

    def seed_ratchet(self, ratchet: dict) -> None:
        """A ratchet list the run was opened with (from the sweep after calibration)."""
        with self._lock:
            self._extra["ratchet"] = dict(ratchet)
            self._publish()

    def log(self, line: str) -> None:
        self._ctx.log(line)

    def finish(self, completed: bool) -> None:
        with self._lock:
            self._extra["step"] = "done"
            self._extra["completed"] = completed
            self._publish()


class _LiveCurrents(Operation):
    """Holds the run's currents and applies "current:<key>=<mA>" inputs: stored
    for the next step that uses them, and written at once when that step is live."""

    kind = "guided_tension"

    def __init__(self, params: dict):
        super().__init__(params)
        self.currents = dict(params.get("defaults") or default_currents(None))
        self.currents.update(
            {k: v for k, v in params.items() if k in CURRENT_BOUNDS_MA}
        )
        self.scoring = params.get("scoring") or SCORING_FRACTION
        self.pass_fractions = {g: DEFAULT_PASS_FRACTION for g in PASS_GROUPS}
        self.pass_fractions.update(params.get("pass_fractions") or {})
        self.pass_slack = dict(DEFAULT_PASS_SLACK_DEG)
        self.pass_slack.update(params.get("pass_slack_deg") or {})
        self._again: set[str] = set()
        self._again_lock = threading.Lock()
        self._hand = None
        self._presenter: _Presenter | None = None
        self._answered = False

    def _new_prompt(self) -> None:
        self._answered = False

    def hold_for(self, joint: str) -> float:
        return self.currents[f"hold_{joint_group(joint)}"]

    @property
    def slack_scoring(self) -> bool:
        return self.scoring == SCORING_SLACK

    def pass_fraction(self, joint: str) -> float:
        return self.pass_fractions[joint_group(joint)]

    def pass_slack_deg(self, joint: str) -> float:
        return self.pass_slack[joint_group(joint)]

    def settings(self) -> dict:
        return {
            **self.currents,
            "scoring": self.scoring,
            "pass_fractions": dict(self.pass_fractions),
            "pass_slack_deg": dict(self.pass_slack),
        }

    def _set_pass(self, value: str) -> None:
        group, _, raw = value[len(PASS_INPUT) :].partition("=")
        low, high = PASS_BOUNDS_DEG if self.slack_scoring else PASS_BOUNDS_FRACTION
        try:
            number = float(raw)
            if group not in PASS_GROUPS or not low <= number <= high:
                raise ValueError("unknown group or out of range")
        except ValueError as e:
            logger.warning("ignored pass threshold change %r: %s", value, e)
            return
        if self.slack_scoring:
            self.pass_slack[group] = number
            shown, text = {"pass_slack_deg": dict(self.pass_slack)}, f"slack tolerance set to {number:g}°"
        else:
            self.pass_fractions[group] = number
            shown, text = {"pass_fractions": dict(self.pass_fractions)}, f"pass threshold set to {number:.0%}"
        if self._presenter is not None:
            self._presenter.set_currents(shown)
            self._presenter.log(f"{group.upper()} {text}")

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_guided_tension_params(service, params)

    def _reboot(self, raw: str) -> None:
        """Clear one latched motor while the routine waits on its prompt."""
        hand, presenter = self._hand, self._presenter
        try:
            motor = int(raw)
        except ValueError:
            logger.warning("ignored reboot request %r", raw)
            return
        if hand is None or presenter is None:
            logger.warning("no hand to reboot motor %d on", motor)
            return
        joint = hand.config.motor_to_joint_dict.get(motor)
        presenter.log(f"rebooting motor {motor} ({joint})")
        try:
            remaining = hand_ops.reboot_held_motor(hand, motor)
        except Exception as e:
            presenter.log(f"motor {motor} reboot failed: {e}")
            return
        if remaining is None:
            presenter.log(f"motor {motor} did not answer after its reboot — check its cable and power")
        elif remaining:
            presenter.log(
                f"motor {motor} re-latched {' + '.join(remaining)} at once — the cause is still there"
            )
            presenter.relatched(motor, joint, remaining)
        else:
            # The routine confirms on its next sweep; the dialog need not wait for it.
            presenter.progress({"event": "fault_cleared", "motor": motor, "joint": joint})

    def drain_again(self) -> set[str]:
        """The joints asked to be tested again since the last call."""
        with self._again_lock:
            joints, self._again = self._again, set()
        return joints

    def handle_input(self, value: str) -> bool:
        if value.startswith(AGAIN_INPUT):
            joint = value[len(AGAIN_INPUT):]
            with self._again_lock:
                self._again.add(joint)
            if self._presenter is not None:
                self._presenter.log(f"{joint}: tested again, its earlier pass dropped")
            return True
        if value.startswith(REBOOT_INPUT):
            self._reboot(value[len(REBOOT_INPUT):])
            return True
        if not value.startswith((PASS_INPUT, CURRENT_INPUT)):
            # One answer per prompt: a double click must not answer the next one too.
            if self._answered:
                return True
            self._answered = True
            return False
        if value.startswith(PASS_INPUT):
            self._set_pass(value)
            return True
        if not value.startswith(CURRENT_INPUT):
            return False
        key, _, raw = value[len(CURRENT_INPUT) :].partition("=")
        presenter = self._presenter
        try:
            current = float(raw)
            low, high = CURRENT_BOUNDS_MA[key]
            if not low <= current <= high:
                raise ValueError(
                    f"{key} must be between {low:.0f} and {high:.0f}{_unit(key)}"
                )
        except (KeyError, ValueError) as e:
            logger.warning("ignored current change %r: %s", value, e)
            return True
        self.currents[key] = current
        if presenter is not None:
            presenter.set_currents({key: current})
            presenter.log(f"{key.replace('_', ' ')} set to {current:.0f}{_unit(key)}")
            hand = self._hand
            if hand is not None and presenter.step == LIVE_STEP.get(key):
                if key == "tension_current":
                    hand_ops.set_max_current(hand, current)
                else:
                    hand_ops.set_joint_currents(hand, self.hold_for)
        return True


class GuidedTensionOperation(_LiveCurrents):
    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        # Read before the lease: in maintenance the session (and its family) is gone.
        family = motor_family(ctx.service)
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        config = supervisor.config
        extra = {
            **self.settings(),
            "hold_fixed": fixed_holds(config, family),
            "deg_per_click": reference.deg_per_click(),
        }
        presenter = self._presenter = _Presenter(
            ctx, extra, self._new_prompt, start_at=self.params.get("start_at")
        )
        if self.params.get("ratchet_joints") is not None:
            presenter.seed_ratchet(self.params["ratchet_joints"])
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config,
                ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None,
            )
            self._hand = hand
            baseline, travel = active_travel_baseline(supervisor.config, family)
            if travel:
                hand_ops.override_travel(hand, travel)
            presenter.set_currents({"baseline": baseline})
            ctx.log(f"scoring against {baseline['label']}")
            result = hand_ops.guided_tension(
                hand,
                prompt_callback=presenter.prompt,
                progress_callback=presenter.progress,
                should_stop=ctx.stop_event.is_set,
                hold_current=self.hold_for,
                tension_current=lambda: self.currents["tension_current"],
                tension_offset_deg=lambda: self.currents["tension_offset_deg"],
                scoring=self.scoring,
                pass_fraction=self.pass_fraction,
                pass_slack_deg=self.pass_slack_deg,
                hand_key=supervisor.hand_id,
                resume=self.params.get("resume", True),
                any_hardware=self.params.get("any_hardware", False),
                forget=self.drain_again,
            )
            presenter.finish(result["completed"])
            ctx.set_phase("released", detail="torque off, control mode restored")
            return result
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()


# ----- simulated (mock) ---------------------------------------------------------


def active_travel_baseline(config, family: str | None) -> tuple[dict, dict[str, float] | None]:
    """(what the dialog shows, the travel table to score against): the hand's
    active baseline, else the shipped reference hand's, else None for the
    config's own v2.1 block."""
    from orca_ui.hand import baselines

    found = baselines.active_baseline(config)
    if found is None:
        shipped = reference.travel(config, family)
        if shipped:
            ref = reference.entry(config, family)
            return {
                "name": ref.get("travel_from"),
                "source": "reference",
                "joints": len(shipped),
                "label": f"the reference hand {ref.get('hand_key')} ({ref.get('travel_from')})",
            }, shipped
        return {
            "name": None,
            "source": "shared",
            "label": "the shared v2.1 baseline",
        }, None
    name, entry = found
    travel = dict(entry.get("travel") or {})
    return (
        {
            "name": name,
            "source": entry.get("source"),
            "recorded_at": entry.get("recorded_at"),
            "joints": len(travel),
            "label": f"baseline {name} ({entry.get('source')})",
        },
        travel,
    )


def _sim_targets(
    config, any_hardware: bool = False, travel: dict[str, float] | None = None
) -> list[dict]:
    travel = travel or {}
    return [
        {
            "joint": j,
            "motor": config.joint_to_motor_map[j],
            "expected_deg": travel.get(
                j, config.expected_motor_travel_deg(j, any_hardware=any_hardware)
            ),
        }
        for j in config.joint_ids
        if j != "wrist" and j in config.joint_to_motor_map
    ]


def _sim_next(passed: list[bool], start: int) -> int:
    return next((j for j in range(start, len(passed)) if not passed[j]), len(passed))


def _sim_previous(passed: list[bool], index: int) -> int | None:
    return next((j for j in range(index - 1, -1, -1) if not passed[j]), None)


def _sim_score(motors: list[dict], threshold, scoring: str) -> dict:
    """The routine's row shape for synthetic spreads, under either scoring."""
    slack_mode = scoring == SCORING_SLACK
    motors = [dict(m) for m in motors]
    for m in motors:
        spread = m["plus_deg"] - m["minus_deg"]
        expected = m["expected_deg"]
        m["spread_deg"] = round(spread, 2)
        live = round(spread / expected, 3) if expected else None
        m["live_fraction"] = live
        kept = m.get("kept")
        m["fraction"] = live if (live is None or kept is None or slack_mode) else max(live, kept)
        m["slack_deg"] = round(expected - spread, 2) if expected else None
        m["scoring"] = scoring
        m["pass_fraction"] = None if slack_mode else threshold(m["joint"])
        m["pass_slack_deg"] = threshold(m["joint"]) if slack_mode else None
        m.setdefault("kept", None)
        m.setdefault("confirmed", False)
        m.setdefault("fault", None)
        # The sim has no end tracker: both ends count as visited twice once confirmed.
        hits = 2 if m["confirmed"] else (1 if spread > 0 else 0)
        m["plus_hits"], m["minus_hits"] = hits, hits
        f, slack = m["fraction"], m["slack_deg"]
        if f is None:
            m["status"] = "unscored"
        elif slack_mode:
            m["status"] = (
                ("pass" if m["confirmed"] else "unconfirmed")
                if slack <= m["pass_slack_deg"]
                else "partial" if (live or 0) >= 0.3 else "low"
            )
        else:
            m["status"] = (
                "pass" if f >= m["pass_fraction"] else "partial" if f >= 0.3 else "low"
            )
    scored = [m for m in motors if m["fraction"] is not None]
    passed = sum(m["status"] == "pass" for m in scored)
    return {
        "motors": motors,
        "passed": passed,
        "scored": len(scored),
        "fraction": passed / len(scored) if scored else 0.0,
        "excluded": [],
    }


class SimulatedGuidedTensionOperation(_LiveCurrents):
    """Plays the real event/prompt sequence with synthetic spreads that grow
    each round, so the dialog can be exercised without a hand. Progress is
    kept in memory for the life of the mock console."""

    # Saved progress per scoring, as the real routine keeps it in setup.yaml.
    _progress: dict = {}
    _progress_slack: dict = {}

    @classmethod
    def progress_for(cls, scoring: str) -> dict:
        return cls._progress_slack if scoring == SCORING_SLACK else cls._progress

    @classmethod
    def _set_progress(cls, scoring: str, record: dict) -> None:
        if scoring == SCORING_SLACK:
            cls._progress_slack = record
        else:
            cls._progress = record

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        family = motor_family(ctx.service)
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        slack = self.slack_scoring
        threshold = self.pass_slack_deg if slack else self.pass_fraction
        extra = {
            **self.settings(),
            "hold_fixed": fixed_holds(supervisor.config, family),
            "deg_per_click": reference.deg_per_click(),
        }
        presenter = self._presenter = _Presenter(
            ctx, extra, self._new_prompt, start_at=self.params.get("start_at")
        )
        if self.params.get("ratchet_joints") is not None:
            presenter.seed_ratchet(self.params["ratchet_joints"])
        baseline, travel = active_travel_baseline(supervisor.config, family)
        presenter.set_currents({"baseline": baseline})
        ctx.log(f"scoring against {baseline['label']}")
        targets = _sim_targets(
            supervisor.config, self.params.get("any_hardware", False), travel
        )
        if not self.params.get("resume", True):
            self._set_progress(self.scoring, {})
        saved = self.progress_for(self.scoring)
        best = {} if slack else dict(saved.get("best", {}))
        if saved:
            presenter.progress(
                {
                    "event": "resumed",
                    **({"scores": dict(saved.get("scores", {}))} if slack else {"best": dict(best)}),
                    "rounds": saved.get("rounds", 0),
                    "updated_at": saved.get("updated_at"),
                }
            )
        reach = {t["joint"]: random.uniform(0.25, 0.95) for t in targets}
        stages = hand_ops.range_stages()
        keys = [st["key"] for st in stages]
        stage_of = {f"{GOTO}{k}": j for j, k in enumerate(keys)}
        goto = lambda skip=None: [f"{GOTO}{k}" for j, k in enumerate(keys) if j != skip]  # noqa: E731
        start = None
        try:
            round_no = 0
            while True:
                round_no += 1
                for joint in self.drain_again():
                    best.pop(joint, None)
                motors = [
                    dict(t, offset_deg=0.0, plus_deg=0.0, minus_deg=0.0, confirmed=False,
                         kept=best.get(t["joint"]))
                    for t in targets
                ]
                scored = {
                    m["joint"]: m
                    for m in _sim_score(motors, threshold, self.scoring)["motors"]
                }
                passed = [
                    all(
                        scored[j]["status"] == "pass"
                        for j in st["joints"]
                        if j in scored
                    )
                    for st in stages
                ]
                i = _sim_next(passed, 0) if start is None else start
                while True:
                    jump = None
                    while i < len(stages):
                        stage = stages[i]
                        info = {
                            "stage": stage,
                            "stage_index": i,
                            "stage_count": len(stages),
                            "round": round_no,
                        }
                        nav = goto(i) + [GOTO_SCORE, GOTO_TENSION]
                        back = _sim_previous(passed, i)
                        presenter.progress({"event": "step", "step": "pose", **info})
                        answer = presenter.prompt(
                            {
                                "action": "pose",
                                "options": ["Continue"]
                                + (["Back"] if back is not None else [])
                                + nav,
                                **info,
                            }
                        )
                        if answer in (GOTO_SCORE, GOTO_TENSION):
                            jump = answer
                            break
                        if answer != "Continue":
                            i = back if answer == "Back" else stage_of[answer]
                            continue
                        presenter.progress({"event": "step", "step": "range", **info})
                        done = threading.Event()
                        sampler = threading.Thread(
                            target=self._sample,
                            args=(
                                presenter,
                                motors,
                                reach,
                                round_no,
                                done,
                                set(stage["joints"]),
                                best,
                                threshold,
                            ),
                            daemon=True,
                        )
                        sampler.start()
                        try:
                            last = _sim_next(passed, i + 1) == len(stages)
                            answer = presenter.prompt(
                                {
                                    "action": "range_check",
                                    "options": ["Score" if last else "Next", "Back"]
                                    + nav,
                                    **info,
                                }
                            )
                        finally:
                            done.set()
                            sampler.join()
                        if answer in (GOTO_SCORE, GOTO_TENSION):
                            jump = answer
                            break
                        if answer != "Back":
                            i = stage_of.get(answer, _sim_next(passed, i + 1))

                    result = _sim_score(motors, threshold, self.scoring)
                    record = {
                        "rounds": self.progress_for(self.scoring).get("rounds", 0) + 1,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                    if slack:
                        record["scores"] = {
                            m["joint"]: {k: m[k] for k in ("slack_deg", "fraction", "status")}
                            for m in result["motors"]
                            if m["slack_deg"] is not None
                        }
                    else:
                        for m in result["motors"]:
                            if m["fraction"] is not None:
                                best[m["joint"]] = max(best.get(m["joint"], 0.0), m["fraction"])
                        record["best"] = dict(best)
                    self._set_progress(self.scoring, record)
                    completed = (
                        result["scored"] > 0 and result["passed"] == result["scored"]
                    )
                    if jump == GOTO_TENSION:
                        presenter.progress(
                            {"event": "score", "round": round_no, **result}
                        )
                        answer = "Tension"
                        break
                    presenter.progress(
                        {"event": "step", "step": "score", "round": round_no}
                    )
                    presenter.progress({"event": "score", "round": round_no, **result})
                    options = ["Finish"] if completed else ["Tension", "Finish anyway"]
                    back = _sim_previous(passed, len(stages))
                    options += (
                        (["Back"] if back is not None else []) + goto() + [GOTO_TENSION]
                    )
                    answer = presenter.prompt(
                        {"action": "score", "options": options, "round": round_no}
                    )
                    if answer == GOTO_TENSION:
                        answer = "Tension"
                    if answer == "Back" or answer in stage_of:
                        i = back if answer == "Back" else stage_of[answer]
                        continue
                    break
                if answer != "Tension":
                    break
                presenter.progress(
                    {"event": "step", "step": "tension", "round": round_no}
                )
                pulled = self.currents["tension_offset_deg"]
                while True:
                    presenter.progress({"event": "pulled", "total_deg": pulled})
                    answer = presenter.prompt(
                        {
                            "action": "tension",
                            "options": ["Done", "Pull more"] + goto(),
                            "round": round_no,
                            "tension_current": self.currents["tension_current"],
                        }
                    )
                    if answer != "Pull more":
                        break
                    pulled += EXTRA_DEG
                start = stage_of.get(answer)
                reach = {
                    j: min(1.0, r + random.uniform(0.15, 0.4)) for j, r in reach.items()
                }
            if completed:
                self._set_progress(self.scoring, {})
            presenter.finish(completed)
            return {"completed": completed, "rounds": round_no}
        finally:
            supervisor.exit_maintenance()

    def _sample(self, presenter, motors, reach, round_no, done, joints: set, best: dict, threshold) -> None:
        start = time.monotonic()
        while not done.wait(0.05):
            t = time.monotonic() - start
            again = self.drain_again()
            for m in motors:
                if m["joint"] in again:
                    best.pop(m["joint"], None)
                    m.update(kept=None, plus_deg=0.0, minus_deg=0.0, confirmed=False)
            for i, m in enumerate(motors):
                if not m["expected_deg"] or m["joint"] not in joints:
                    continue
                half = m["expected_deg"] * reach[m["joint"]] / 2
                envelope = min(1.0, t / (4.0 + i * 0.3))
                m["offset_deg"] = round(half * envelope * math.sin(t * 2.5 + i), 2)
                m["plus_deg"] = max(m["plus_deg"], m["offset_deg"])
                m["minus_deg"] = min(m["minus_deg"], m["offset_deg"])
                # Both ends have been visited twice once the full envelope has cycled.
                m["confirmed"] = t > 4.0 + i * 0.3 + 2 * math.pi / 2.5
            presenter.progress(
                {
                    "event": "spread",
                    "round": round_no,
                    **_sim_score(motors, threshold, self.scoring),
                }
            )

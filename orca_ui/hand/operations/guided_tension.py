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

from orca_ui.hand import probes
from orca_ui.hand.faults import classify_hw_error
from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.tension import DEFAULT_TENSION_OFFSET_DEG, EXTRA_DEG

logger = logging.getLogger(__name__)

PROMPTS = {
    "pose": "Torque off — pose the hand for the next finger",
    "range_check": "Drive the highlighted joints through their full range",
    "score": "Range check scored",
    "check_pose": "Torque off — bring the hand to the pose shown, clear of every stop",
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
PASS_GROUPS = ("ap", "mcp", "pip")
# Which rule scores the range check (see run_guided_tension): "fraction" is
# the spread as a share of the expected travel with the best kept across
# rounds; "slack" is expected minus a settled, twice-reached spread, in degrees.
SCORING_FRACTION = "fraction"
SCORING_SLACK = "slack"
SCORINGS = (SCORING_FRACTION, SCORING_SLACK)
PASS_BOUNDS_FRACTION = (0.1, 1.0)
DEFAULT_PASS_FRACTION = 0.85
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
    # Opened from a tension check: carry its results and go straight to the ratchet.
    check_from = params.get("check_from")
    if check_from is not None:
        if probes.state(config)["probes"].get(check_from) is None:
            raise ServiceError(f"no probe dataset named {check_from!r}", status_code=422)
        clean["check_from"] = str(check_from)
    start_at = params.get("start_at")
    if start_at not in (None, "tension"):
        raise ServiceError("start_at must be 'tension' or omitted", status_code=422)
    if start_at is not None:
        clean["start_at"] = start_at
    # Begin with the tension check and its ratchet before any finger is moved.
    clean["check_first"] = bool(params.get("check_first", False))
    # Tendons to ratchet, with their share of the reference, from a measurement
    # (the sweep after calibration) rather than a check.
    ratchet = params.get("ratchet_joints")
    if ratchet is not None:
        known = set(config.joint_ids) - {"wrist"}
        if not isinstance(ratchet, dict) or not set(ratchet) <= known:
            raise ServiceError("ratchet_joints must map this hand's finger joints to a percentage", status_code=422)
        clean["ratchet_joints"] = {j: (float(v) if v is not None else None) for j, v in ratchet.items()}
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

    def __init__(self, ctx: OpContext, currents: dict, on_prompt=None, clicks: dict | None = None,
                 start_at: str | None = None):
        self._ctx = ctx
        self._on_prompt = on_prompt
        self._clicks = clicks or {}
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
        """Add the ratchet clicks the click model says this joint's slack needs."""
        if not self._clicks:
            return motor
        slack = motor.get("slack_deg")
        if motor.get("probe_slack_deg") is not None:
            slack = max(slack or 0.0, motor["probe_slack_deg"])
        return {**motor, "clicks_left": probes.clicks_left(self._clicks, motor["joint"], slack)}

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
            self._ctx.log("opened from a tension check: straight to the ratchet")
            return GOTO_TENSION
        self._start_at = None
        return self._ctx.wait_input(PROMPTS[action], list(prompt["options"]))

    def check_update(self, extra: dict) -> None:
        """The tension check running inside this round, as the probe presenter publishes it."""
        with self._lock:
            self._extra["check"] = {**extra, "round": self._extra["round"]}
            self._publish()

    def seed_ratchet(self, ratchet: dict) -> None:
        """A ratchet list the run was opened with (from the sweep after calibration)."""
        with self._lock:
            self._extra["ratchet"] = dict(ratchet)
            self._publish()

    def seed_check(self, config, name: str) -> None:
        """Show a saved check's results from the start (opened from its dialog)."""
        dataset = probes.state(config)["probes"].get(name)
        if not dataset:
            return
        with self._lock:
            self._extra["check"] = {
                "step": "done", "check": True, "saved": name, "methods": dataset.get("methods", ["breakaway"]),
                "joints": dataset.get("joints", []), "repeats": dataset.get("repeats", 1),
                "results": list(dataset.get("results", [])), "index": 0, "done": 0, "total": 0,
                "current": None, "active": [], "centre_deg": dataset.get("centre_deg", {}),
                "round": 0,
            }
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

    def handle_input(self, value: str) -> bool:
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
        from orca_ui.hand.operations.tension_probe import hand_family

        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        config = supervisor.config
        slack = self.slack_scoring
        clicks = _click_model(config) if slack else {}
        extra = {
            **self.settings(),
            "hold_fixed": fixed_holds(config, motor_family(ctx.service)),
        }
        if slack:
            extra["clicks"] = clicks
        presenter = self._presenter = _Presenter(
            ctx, extra, self._new_prompt, clicks, start_at=self.params.get("start_at")
        )
        if self.params.get("check_from"):
            presenter.seed_check(config, self.params["check_from"])
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
            family = hand_family(hand)
            probe = None
            if slack:
                baseline, travel = active_travel_baseline(supervisor.config)
                if travel:
                    hand_ops.override_travel(hand, travel)
                presenter.set_currents({"baseline": baseline})
                ctx.log(f"scoring against {baseline['label']}")
                probe = _probe_slack(config, supervisor.hand_id)
            if probe is not None:
                name, slack = probe
                flagged = sorted(j for j, v in slack.items() if v > self.pass_slack_deg(j))
                presenter.set_currents(
                    {"probe": {"name": name, "joints": len(slack), "flagged": flagged}}
                )
                ctx.log(
                    f"probe {name} measured slack on {len(slack)} joints; "
                    + (f"{', '.join(flagged)} must be tensioned this round"
                       if flagged else "none above tolerance")
                )
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
                probe_slack_deg=probe[1] if probe else None,
                hand_key=supervisor.hand_id,
                resume=self.params.get("resume", True),
                any_hardware=self.params.get("any_hardware", False),
                check_callback=lambda h: run_check(ctx, h, presenter, family),
                check_first=self.params.get("check_first", False),
            )
            presenter.finish(result["completed"])
            ctx.set_phase("released", detail="torque off, control mode restored")
            return result
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()


def run_check(ctx: OpContext, hand, presenter: _Presenter, family: str | None) -> None:
    """The tension check between the range check and the ratchet: the breakaway
    probe from where the hand stands, limits ignored, one pass, one joint kind
    at a time, published under the round's ``check`` and saved as a dataset."""
    from orca_ui.hand.operations.tension_probe import CHECK_PARAMS, _Presenter as _ProbePresenter, run_probe

    params = {**CHECK_PARAMS, "note": f"guided tensioning round {presenter._extra['round']}"}
    probe_presenter = _ProbePresenter(ctx, params["methods"], check=True, publish=presenter.check_update)
    ctx.log("tension check: breakaway from where the hand stands, limits ignored")
    run_probe(ctx, hand, params, probe_presenter, family)


# ----- simulated (mock) ---------------------------------------------------------


def _probe_slack(config, hand_key: str | None) -> tuple[str, dict[str, float]] | None:
    """Slack the hand's newest probe measured, if it is newer than its last tensioning."""
    try:
        last = hand_ops.last_tension(config) or {}
        return probes.probe_slack(config, hand_key, since=last.get("completed_at"))
    except Exception:
        logger.exception("reading the tension probe failed")
        return None


def _click_model(config) -> dict:
    try:
        return probes.click_model(config)
    except Exception:
        logger.exception("reading the click tests failed")
        return {}


def active_travel_baseline(config) -> tuple[dict, dict[str, float] | None]:
    """(what the dialog shows, the travel table to score against or None for
    the config's own baseline)."""
    from orca_ui.hand import baselines

    found = baselines.active_baseline(config)
    if found is None:
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
        m.setdefault("probe_slack_deg", None)
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

    # Saved progress per scoring, as the real routine keeps it in tension_progress.yaml.
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
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        slack = self.slack_scoring
        threshold = self.pass_slack_deg if slack else self.pass_fraction
        clicks = _click_model(supervisor.config) if slack else {}
        extra = {
            **self.settings(),
            "hold_fixed": fixed_holds(supervisor.config, motor_family(ctx.service)),
        }
        if slack:
            extra["clicks"] = clicks
        presenter = self._presenter = _Presenter(
            ctx, extra, self._new_prompt, clicks, start_at=self.params.get("start_at")
        )
        if self.params.get("check_from"):
            presenter.seed_check(supervisor.config, self.params["check_from"])
        if self.params.get("ratchet_joints") is not None:
            presenter.seed_ratchet(self.params["ratchet_joints"])
        travel = None
        if slack:
            baseline, travel = active_travel_baseline(supervisor.config)
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
                first = self.params.get("check_first", False) and round_no == 1
                while True:
                    jump = None
                    if first:
                        first = False
                        i = len(stages)
                        jump = "Check & tension"
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
                    if jump != "Check & tension":
                        self._set_progress(self.scoring, record)
                    completed = (
                        result["scored"] > 0 and result["passed"] == result["scored"]
                    )
                    if jump in (GOTO_TENSION, "Check & tension"):
                        presenter.progress(
                            {"event": "score", "round": round_no, **result}
                        )
                        answer = "Tension" if jump == GOTO_TENSION else "Check & tension"
                        break
                    presenter.progress(
                        {"event": "step", "step": "score", "round": round_no}
                    )
                    presenter.progress({"event": "score", "round": round_no, **result})
                    options = ["Finish"] if completed else ["Check & tension", "Finish anyway"]
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
                if answer == "Check & tension":
                    presenter.progress({"event": "step", "step": "check_pose", "round": round_no})
                    if presenter.prompt({"action": "check_pose", "options": ["Continue", "Skip check"],
                                         "round": round_no}) == "Continue":
                        presenter.progress({"event": "step", "step": "check", "round": round_no})
                        self._simulate_check(ctx, presenter, reach)
                    answer = "Tension"
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

    def _simulate_check(self, ctx: OpContext, presenter: _Presenter, reach: dict) -> None:
        """The in-round tension check on the mock: joints that reached little of
        their travel read as slack tendons."""
        from orca_ui.hand.operations.simulated import _sim_step_duration
        from orca_ui.hand.operations.tension_probe import CHECK_PARAMS, _Presenter as _ProbePresenter, simulate_probe

        params = {**CHECK_PARAMS, "step_duration_s": _sim_step_duration(self.params),
                  "note": f"guided tensioning round {presenter._extra['round']}"}
        probe_presenter = _ProbePresenter(ctx, params["methods"], check=True, publish=presenter.check_update)
        slack = {j: max(0.0, (1.0 - r) * 15.0) for j, r in reach.items()}
        simulate_probe(ctx, ctx.service.supervisor.config, params, probe_presenter, slack)

    def _sample(self, presenter, motors, reach, round_no, done, joints: set, threshold) -> None:
        start = time.monotonic()
        while not done.wait(0.05):
            t = time.monotonic() - start
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

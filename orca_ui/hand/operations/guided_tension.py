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
GOTO = "goto:"  # answer prefix that jumps to a range stage by key, or to score / tension
GOTO_SCORE = f"{GOTO}score"
GOTO_TENSION = f"{GOTO}tension"
PUBLISH_PERIOD_S = 0.1
HOLD_BOUNDS_MA = (20.0, 500.0)
# Run settings: currents in mA, and how far the motors turn counterclockwise while tensioning in degrees.
CURRENT_BOUNDS_MA = {"hold_ap": HOLD_BOUNDS_MA, "hold_mcp": HOLD_BOUNDS_MA,
                     "hold_pip": HOLD_BOUNDS_MA,
                     "tension_offset_deg": (0.0, 45.0)}
# Range-check holds per joint group, in mA. The Feetech values match the Dynamixel
# output torque (Feetech draws ~275 mA before producing any). The ratcheting hold
# is not here: orca_core runs it at each motor's own goal-current ceiling, because a
# position loop at its goal draws nothing and the ceiling is the whole budget it has
# to refuse being turned with.
DEFAULT_CURRENTS_MA = {
    "dynamixel": {"hold_ap": 200.0, "hold_mcp": 140.0, "hold_pip": 100.0},
    "feetech": {"hold_ap": 380.0, "hold_mcp": 320.0, "hold_pip": 280.0},
}


# Input values "current:<key>=<mA>" change a current mid-run instead of answering a prompt.
CURRENT_INPUT = "current:"
LIVE_STEP = {"hold_ap": "range", "hold_mcp": "range", "hold_pip": "range"}
# Input values "pass:<group>=<fraction>" change a group's pass threshold mid-run.
PASS_INPUT = "pass:"
PASS_GROUPS = ("ap", "mcp", "pip")
PASS_BOUNDS = (0.1, 1.0)
DEFAULT_PASS_FRACTION = 0.85


def default_currents(motor_type: str | None) -> dict:
    return {**DEFAULT_CURRENTS_MA.get(motor_type or "", DEFAULT_CURRENTS_MA["dynamixel"]),
            "tension_offset_deg": DEFAULT_TENSION_OFFSET_DEG}


def _unit(key: str) -> str:
    return "°" if key.endswith("_deg") else " mA"


def motor_family(service) -> str | None:
    """The connected hand's motor family, as resolved at connect."""
    session = service.session
    config = session.hand.config if session is not None else service.supervisor.config
    family = getattr(config, "motor_type", None)
    return family if family in DEFAULT_CURRENTS_MA else None


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
        raise ServiceError("the installed orca_core has no guided tensioning", status_code=409)
    clean = {}
    for key, (low, high) in CURRENT_BOUNDS_MA.items():
        if params.get(key) is None:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            raise ServiceError(f"{key} must be a number", status_code=422)
        if not low <= value <= high:
            raise ServiceError(f"{key} must be between {low:.0f} and {high:.0f}{_unit(key)}",
                               status_code=422)
        clean[key] = value
    passes = params.get("pass_fractions") or {}
    if not isinstance(passes, dict) or not set(passes) <= set(PASS_GROUPS):
        raise ServiceError(f"pass_fractions must map {', '.join(PASS_GROUPS)} to a fraction",
                           status_code=422)
    for group, value in passes.items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ServiceError(f"pass_fractions.{group} must be a number", status_code=422)
        if not PASS_BOUNDS[0] <= value <= PASS_BOUNDS[1]:
            raise ServiceError(f"pass_fractions.{group} must be between 10% and 100%",
                               status_code=422)
        clean.setdefault("pass_fractions", {})[group] = value
    clean["resume"] = bool(params.get("resume", True))
    clean["any_hardware"] = bool(params.get("any_hardware", False))
    config = service.supervisor.config
    if not (getattr(config, "uses_motor_travel", True) or clean["any_hardware"]):
        raise ServiceError(
            "guided tensioning needs v2.1 hardware — use the hold dialog, or "
            "force guided in the tension settings", status_code=409)
    clean["defaults"] = default_currents(motor_family(service))
    return clean


class _Presenter:
    """Turns the routine's prompts and progress events into snapshot updates."""

    def __init__(self, ctx: OpContext, currents: dict, on_prompt=None):
        self._ctx = ctx
        self._on_prompt = on_prompt
        self._extra: dict = {"step": "pose", "round": 1, "motors": [], "history": [],
                             "stages": hand_ops.range_stages(), **currents}
        self._lock = threading.Lock()
        self._last_publish = 0.0
        self._rounds_before = 0

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

    def _round(self, run_round: int) -> int:
        """The routine numbers rounds per run; the operator counts across resumes."""
        return int(run_round) + self._rounds_before

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "step":
                round_no = self._round(event["round"])
                if round_no != self._extra["round"]:
                    self._extra.update(motors=[], passed=0, scored=0, fraction=0.0)
                self._extra.update(step=event["step"], round=round_no)
                if "stage" in event:
                    self._extra.update({k: event[k] for k in ("stage", "stage_index", "stage_count")})
                if "absent_joints" in event:
                    absent = set(event["absent_joints"])
                    self._extra["absent_joints"] = sorted(absent)
                    # The routine drops a stage with no present joint; the sidebar does too.
                    self._extra["stages"] = [st for st in hand_ops.range_stages()
                                             if any(j not in absent for j in st["joints"])]
                self._publish()
            elif kind in ("spread", "score"):
                self._extra.update({k: event[k] for k in ("motors", "passed", "scored", "fraction")})
                if "excluded" in event:
                    self._extra["excluded"] = list(event["excluded"])
                if kind == "score":
                    round_no = self._round(event["round"])
                    self._extra["history"] = self._extra["history"] + [
                        {"round": round_no, **{k: event[k] for k in ("passed", "scored", "fraction")}}]
                    self._ctx.log(f"round {round_no}: {event['passed']}/{event['scored']} "
                                  f"motors reached their travel")
                self._publish(force=kind == "score")
            elif kind == "pulled":
                self._extra["pulled_deg"] = event["total_deg"]
                self._publish()
            elif kind == "resumed":
                self._rounds_before = int(event["rounds"])
                self._extra["resumed"] = {"rounds": event["rounds"], "updated_at": event.get("updated_at"),
                                          "joints": len(event["best"])}
                self._ctx.log(f"resumed saved progress: {len(event['best'])} joints scored "
                              f"over {event['rounds']} earlier round(s)")
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def prompt(self, prompt: dict) -> str:
        action = prompt["action"]
        with self._lock:
            self._publish()
        self._ctx.set_phase(action, detail=f"round {self._round(prompt.get('round', 1))}")
        if self._on_prompt is not None:
            self._on_prompt()
        return self._ctx.wait_input(PROMPTS[action], list(prompt["options"]))

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
        self.currents.update({k: v for k, v in params.items() if k in CURRENT_BOUNDS_MA})
        self.pass_fractions = {g: DEFAULT_PASS_FRACTION for g in PASS_GROUPS}
        self.pass_fractions.update(params.get("pass_fractions") or {})
        self._hand = None
        self._presenter: _Presenter | None = None
        self._answered = False

    def _new_prompt(self) -> None:
        self._answered = False

    def hold_for(self, joint: str) -> float:
        return self.currents[f"hold_{joint_group(joint)}"]

    def pass_fraction(self, joint: str) -> float:
        return self.pass_fractions[joint_group(joint)]

    def settings(self) -> dict:
        return {**self.currents, "pass_fractions": dict(self.pass_fractions)}

    def _set_pass(self, value: str) -> None:
        group, _, raw = value[len(PASS_INPUT):].partition("=")
        try:
            fraction = float(raw)
            if group not in PASS_GROUPS or not PASS_BOUNDS[0] <= fraction <= PASS_BOUNDS[1]:
                raise ValueError("unknown group or out of range")
        except ValueError as e:
            logger.warning("ignored pass threshold change %r: %s", value, e)
            return
        self.pass_fractions[group] = fraction
        if self._presenter is not None:
            self._presenter.set_currents({"pass_fractions": dict(self.pass_fractions)})
            self._presenter.log(f"{group.upper()} pass threshold set to {fraction:.0%}")

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_guided_tension_params(service, params)

    def handle_input(self, value: str) -> bool:
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
        key, _, raw = value[len(CURRENT_INPUT):].partition("=")
        presenter = self._presenter
        try:
            current = float(raw)
            low, high = CURRENT_BOUNDS_MA[key]
            if not low <= current <= high:
                raise ValueError(f"{key} must be between {low:.0f} and {high:.0f}{_unit(key)}")
        except (KeyError, ValueError) as e:
            logger.warning("ignored current change %r: %s", value, e)
            return True
        self.currents[key] = current
        if presenter is not None:
            presenter.set_currents({key: current})
            presenter.log(f"{key.replace('_', ' ')} set to {current:.0f}{_unit(key)}")
            hand = self._hand
            if hand is not None and presenter.step == LIVE_STEP.get(key):
                hand_ops.set_joint_currents(hand, self.hold_for)
        return True


class GuidedTensionOperation(_LiveCurrents):
    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        presenter = self._presenter = _Presenter(ctx, self.settings(), self._new_prompt)
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None)
            self._hand = hand
            result = hand_ops.guided_tension(
                hand,
                prompt_callback=presenter.prompt,
                progress_callback=presenter.progress,
                should_stop=ctx.stop_event.is_set,
                hold_current=self.hold_for,
                tension_offset_deg=lambda: self.currents["tension_offset_deg"],
                pass_fraction=self.pass_fraction,
                hand_key=supervisor.hand_id,
                resume=self.params.get("resume", True),
                any_hardware=self.params.get("any_hardware", False),
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


def _sim_targets(config, any_hardware: bool = False) -> list[dict]:
    return [
        {"joint": j, "motor": config.joint_to_motor_map[j],
         "expected_deg": config.expected_motor_travel_deg(j, any_hardware=any_hardware)}
        for j in config.joint_ids
        if j != "wrist" and j in config.joint_to_motor_map
    ]


def _sim_next(passed: list[bool], start: int) -> int:
    return next((j for j in range(start, len(passed)) if not passed[j]), len(passed))


def _sim_previous(passed: list[bool], index: int) -> int | None:
    return next((j for j in range(index - 1, -1, -1) if not passed[j]), None)


def _sim_score(motors: list[dict], pass_fraction) -> dict:
    motors = [dict(m) for m in motors]
    for m in motors:
        spread = m["plus_deg"] - m["minus_deg"]
        m["spread_deg"] = round(spread, 2)
        live = round(spread / m["expected_deg"], 3) if m["expected_deg"] else None
        m["live_fraction"] = live
        m["fraction"] = live if live is None or m.get("kept") is None else max(live, m["kept"])
        f = m["fraction"]
        m["pass_fraction"] = pass_fraction(m["joint"])
        m["status"] = ("unscored" if f is None else "pass" if f >= m["pass_fraction"]
                       else "partial" if f >= 0.3 else "low")
    scored = [m for m in motors if m["fraction"] is not None]
    passed = sum(m["status"] == "pass" for m in scored)
    return {"motors": motors, "passed": passed, "scored": len(scored),
            "fraction": passed / len(scored) if scored else 0.0, "excluded": []}


class SimulatedGuidedTensionOperation(_LiveCurrents):
    """Plays the real event/prompt sequence with synthetic spreads that grow
    each round, so the dialog can be exercised without a hand. Progress is
    kept in memory for the life of the mock console."""

    _progress: dict = {}

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        presenter = self._presenter = _Presenter(ctx, self.settings(), self._new_prompt)
        targets = _sim_targets(supervisor.config, self.params.get("any_hardware", False))
        best = dict(self._progress.get("best", {})) if self.params.get("resume", True) else {}
        if not self.params.get("resume", True):
            SimulatedGuidedTensionOperation._progress = {}
        if best:
            presenter.progress({"event": "resumed", "best": best,
                                "rounds": self._progress.get("rounds", 0)})
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
                motors = [dict(t, offset_deg=0.0, plus_deg=0.0, minus_deg=0.0,
                               kept=best.get(t["joint"])) for t in targets]
                scored = {m["joint"]: m for m in _sim_score(motors, self.pass_fraction)["motors"]}
                passed = [all(scored[j]["status"] == "pass" for j in st["joints"] if j in scored)
                          for st in stages]
                i = _sim_next(passed, 0) if start is None else start
                while True:
                    jump = None
                    while i < len(stages):
                        stage = stages[i]
                        info = {"stage": stage, "stage_index": i, "stage_count": len(stages),
                                "round": round_no}
                        nav = goto(i) + [GOTO_SCORE, GOTO_TENSION]
                        back = _sim_previous(passed, i)
                        presenter.progress({"event": "step", "step": "pose", **info})
                        answer = presenter.prompt({"action": "pose", "options": ["Continue"]
                                                   + (["Back"] if back is not None else []) + nav,
                                                   **info})
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
                            args=(presenter, motors, reach, round_no, done, set(stage["joints"])),
                            daemon=True)
                        sampler.start()
                        try:
                            last = _sim_next(passed, i + 1) == len(stages)
                            answer = presenter.prompt({"action": "range_check", "options":
                                                       ["Score" if last else "Next", "Back"] + nav,
                                                       **info})
                        finally:
                            done.set()
                            sampler.join()
                        if answer in (GOTO_SCORE, GOTO_TENSION):
                            jump = answer
                            break
                        if answer != "Back":
                            i = stage_of.get(answer, _sim_next(passed, i + 1))

                    result = _sim_score(motors, self.pass_fraction)
                    for m in result["motors"]:
                        if m["fraction"] is not None:
                            best[m["joint"]] = max(best.get(m["joint"], 0.0), m["fraction"])
                    SimulatedGuidedTensionOperation._progress = {
                        "best": dict(best), "rounds": self._progress.get("rounds", 0) + 1,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    completed = result["scored"] > 0 and result["passed"] == result["scored"]
                    if jump == GOTO_TENSION:
                        presenter.progress({"event": "score", "round": round_no, **result})
                        answer = "Tension"
                        break
                    presenter.progress({"event": "step", "step": "score", "round": round_no})
                    presenter.progress({"event": "score", "round": round_no, **result})
                    options = ["Finish"] if completed else ["Tension", "Finish anyway"]
                    back = _sim_previous(passed, len(stages))
                    options += (["Back"] if back is not None else []) + goto() + [GOTO_TENSION]
                    answer = presenter.prompt({"action": "score", "options": options, "round": round_no})
                    if answer == GOTO_TENSION:
                        answer = "Tension"
                    if answer == "Back" or answer in stage_of:
                        i = back if answer == "Back" else stage_of[answer]
                        continue
                    break
                if answer != "Tension":
                    break
                presenter.progress({"event": "step", "step": "tension", "round": round_no})
                pulled = self.currents["tension_offset_deg"]
                while True:
                    presenter.progress({"event": "pulled", "total_deg": pulled})
                    answer = presenter.prompt({"action": "tension", "options": ["Done", "Pull more"]
                                               + goto(), "round": round_no})
                    if answer != "Pull more":
                        break
                    pulled += EXTRA_DEG
                start = stage_of.get(answer)
                reach = {j: min(1.0, r + random.uniform(0.15, 0.4)) for j, r in reach.items()}
            if completed:
                SimulatedGuidedTensionOperation._progress = {}
            presenter.finish(completed)
            return {"completed": completed, "rounds": round_no}
        finally:
            supervisor.exit_maintenance()

    def _sample(self, presenter, motors, reach, round_no, done, joints: set) -> None:
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
            presenter.progress({"event": "spread", "round": round_no,
                                **_sim_score(motors, self.pass_fraction)})

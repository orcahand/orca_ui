"""Tension probe operation: measure every tendon's breakaway current.

Runs orca_core's run_tension_probe under the maintenance lease, one motor at a
time with the others holding, the whole sequence ``repeats`` times so the
currents can be averaged, and saves the report beside the hand's calibration
as a named dataset (``GT_tension_00``, ...). Breakaway is the measurement;
the take-up method only runs when asked for. Live samples stream through the
snapshot ``extra`` (TensionProbeExtra in the frontend types).

With ``ignore_calibration`` the probe is a tension check between tensioning
rounds: it holds the hand where it stands, ignores the stale motor limits and
probes every side the full cap. Less exact than the sweep after calibration,
and meant as advice on which spools to ratchet next. A check first asks the
operator to bring the hand to the mid pose (``pose_prompt``), so no joint
starts against a stop, and ramps the joints of one kind together (``parallel``).
The same check runs inside guided tensioning (see guided_tension.run_check).
"""

from __future__ import annotations

import logging
import random
import threading
import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

logger = logging.getLogger(__name__)

METHODS = ("takeup", "breakaway", "stroke")
DEFAULT_METHODS = ("breakaway",)
DEFAULT_REPEATS = 1
MAX_REPEATS = 10
PUBLISH_PERIOD_S = 0.1
# Settings a run may override, with their bounds (mA or motor degrees).
# Feetech motors need roughly twice the Dynamixel current for the same pull
# (see guided_tension_currents in the hand config), so every current default
# scales with the family; angles and times do not.
FAMILY_CURRENT_SCALE = {"feetech": 2.0}

SETTING_BOUNDS = {
    "hold_current_ma": (20.0, 500.0),
    "pose_current_ma": (20.0, 600.0),
    "pose_tolerance_deg": (1.0, 45.0),
    "takeup_current_ma": (10.0, 300.0),
    "start_current_ma": (5.0, 200.0),
    "step_current_ma": (1.0, 100.0),
    "max_current_ma": (20.0, 600.0),
    "play_deg": (0.5, 20.0),
    "move_deg": (1.0, 60.0),
    "max_travel_deg": (5.0, 90.0),
    "limit_margin_deg": (0.0, 45.0),
    "stroke_current_ma": (20.0, 400.0),
    "stroke_speed_deg_s": (5.0, 90.0),
}


def validate_probe_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — the probe needs motors", status_code=409)
    if not hand_ops.tension_probe_supported():
        raise ServiceError(
            "the installed orca_core has no tension probe", status_code=409
        )
    methods = params.get("methods") or list(DEFAULT_METHODS)
    if not isinstance(methods, list) or not methods or not set(methods) <= set(METHODS):
        raise ServiceError(
            f"methods must be a non-empty subset of {list(METHODS)}", status_code=422
        )
    clean: dict = {"methods": [m for m in METHODS if m in methods]}
    repeats = params.get("repeats", DEFAULT_REPEATS)
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= MAX_REPEATS:
        raise ServiceError(f"repeats must be an integer from 1 to {MAX_REPEATS}", status_code=422)
    clean["repeats"] = repeats
    pose = params.get("pose", "mid")
    if pose not in ("mid", "neutral", "hold"):
        raise ServiceError("pose must be 'mid', 'neutral' or 'hold'", status_code=422)
    clean["ignore_calibration"] = bool(params.get("ignore_calibration", False))
    # Without the limits the only safe start is where the hand stands.
    clean["pose"] = "hold" if clean["ignore_calibration"] else pose
    # One joint kind at a time by default; the operator poses a check by hand first.
    clean["parallel"] = bool(params.get("parallel", True))
    clean["pose_prompt"] = bool(params.get("pose_prompt", clean["ignore_calibration"]))
    config = service.supervisor.config
    joints = params.get("joints")
    if joints is not None:
        known = set(config.joint_ids) - {"wrist"}
        if not isinstance(joints, list) or not joints or not set(joints) <= known:
            raise ServiceError(
                "joints must be a non-empty list of this hand's finger joints", status_code=422
            )
        clean["joints"] = list(joints)
    # Currents may not exceed the hand's own ceiling: the probe pulls on one tendon.
    # The config's max_current may still read "default" before connect resolves it,
    # so fall back to the motor family's register ceiling, then to no ceiling.
    ceiling = _current_ceiling(config, session)
    settings = {}
    for key, (low, high) in SETTING_BOUNDS.items():
        if params.get(key) is None:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            raise ServiceError(f"{key} must be a number", status_code=422)
        if key.endswith("_ma") and ceiling is not None:
            high = min(high, ceiling)
        if not low <= value <= high:
            raise ServiceError(
                f"{key} must be between {low:g} and {high:g}", status_code=422
            )
        settings[key] = value
    clean["settings"] = settings
    name = params.get("name")
    if name is not None:
        from orca_ui.hand.probes import NAME_RE

        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ServiceError("name: 1-40 letters, digits, _ . -", status_code=422)
        clean["name"] = name
    note = params.get("note")
    if note is not None:
        clean["note"] = str(note)[:200]
    return clean


def hand_family(hand) -> str | None:
    """The motor family of an open (maintenance) hand, from its motor client."""
    client = getattr(hand, "motor_client", None)
    family = getattr(type(client), "motor_type", None) if client is not None else None
    return family if isinstance(family, str) else None


def probe_defaults(service, family: str | None = None) -> dict:
    """ProbeSettings defaults for the hand's motor family (``family`` when the
    caller knows it from an open hand; otherwise the session's), clamped to
    the setting bounds and the hand's current ceiling."""
    from orca_ui.hand.operations import hand_ops
    from orca_ui.hand.operations.guided_tension import motor_family

    defaults = hand_ops.probe_setting_defaults()
    scale = FAMILY_CURRENT_SCALE.get(family or motor_family(service) or "", 1.0)
    ceiling = _current_ceiling(service.supervisor.config, service.session)
    for key in list(defaults):
        if not key.endswith("_ma"):
            continue
        value = defaults[key] * scale
        lo, hi = SETTING_BOUNDS.get(key, (0.0, value))
        if ceiling is not None:
            hi = min(hi, ceiling)
        defaults[key] = float(max(lo, min(value, hi)))
    return defaults


def _current_ceiling(config, session) -> float | None:
    """The hand's own current limit in mA, or None if nothing numeric is known."""
    value = getattr(config, "max_current", None)
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    client = getattr(getattr(session, "hand", None), "motor_client", None)
    family_max = getattr(type(client), "max_current_ma", None) if client is not None else None
    return float(family_max) if isinstance(family_max, (int, float)) and family_max > 0 else None


POSE_PROMPT = "Bring the hand to the pose shown, clear of every stop, then continue"
POSE_CONTINUE = "Continue"


class _Presenter:
    """Turns the routine's events into the snapshot the dialog renders.

    ``publish`` replaces the snapshot ``extra`` write when the probe runs inside
    another operation (guided tensioning keeps it under its own ``check``)."""

    def __init__(self, ctx: OpContext, methods: list[str], check: bool = False, publish=None):
        self._ctx = ctx
        self._lock = threading.Lock()
        self._last = 0.0
        self._sink = publish
        self.extra: dict = {
            "step": "starting",
            "methods": methods,
            "check": check,
            "index": 0,
            "done": 0,
            "total": 0,
            "repeats": 1,
            "results": [],
            "current": None,
            "active": [],
            "centre_deg": {},
        }

    def _publish(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last < PUBLISH_PERIOD_S:
            return
        self._last = now
        snapshot = {**self.extra, "results": list(self.extra["results"]), "active": list(self.extra["active"])}
        if self._sink is not None:
            self._sink(snapshot)
        else:
            self._ctx.set_extra(snapshot)

    def pose(self) -> None:
        """Park on the pose prompt until the operator has posed the hand."""
        with self._lock:
            self.extra["step"] = "pose"
            self._publish()
        self._ctx.set_phase("pose", detail="torque off — bring the hand to the pose shown")
        self._ctx.wait_input(POSE_PROMPT, [POSE_CONTINUE])

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "pose_skipped":
                self._ctx.log(f"start pose: {event['reason']}")
            elif kind == "pose_short":
                self.extra["pose_short"] = dict(event["joints"])
                off = ", ".join(f"{j} ({d:g}°)" for j, d in event["joints"].items())
                self._ctx.log(f"start pose not reached on {off}; probing from where they stand")
            elif kind == "probe_plan":
                repeats = int(event.get("repeats", 1))
                self.extra.update(
                    step="probing",
                    total=event["total"],
                    repeats=repeats,
                    joints=event["joints"],
                    centre_deg=event["centre_deg"],
                    pose=event.get("pose"),
                )
                self._ctx.log(
                    f"probing {len(event['joints'])} joints × 2 directions × "
                    f"{len(event['methods'])} method(s)"
                    + (f" × {repeats} passes" if repeats > 1 else "")
                )
                self._publish()
            elif kind == "probe_started":
                run = int(event.get("run", 1))
                entry = {k: event[k] for k in ("joint", "motor", "direction", "sense", "method")}
                entry.update(current_ma=None, deg=0.0, run=run, index=event["index"])
                active = [a for a in self.extra["active"] if a["joint"] != event["joint"]] + [entry]
                self.extra.update(index=event["index"], active=active, current=active[0])
                passes = f"pass {run}/{self.extra['repeats']} · " if self.extra["repeats"] > 1 else ""
                names = ", ".join(a["joint"] for a in active)
                self._ctx.set_phase(
                    "probing",
                    progress=self.extra["done"] / max(event["total"], 1),
                    detail=f"{passes}{names} {event['sense']} · {event['method']}",
                )
                self._publish()
            elif kind == "probe_sample":
                for a in self.extra["active"]:
                    if a["joint"] == event["joint"]:
                        a.update(current_ma=event["current_ma"], deg=round(event["deg"], 2))
                self._publish(force=False)
            elif kind == "probe_done":
                result = event["result"]
                self.extra["results"] = self.extra["results"] + [result]
                self.extra["done"] = len(self.extra["results"])
                active = [a for a in self.extra["active"] if a["joint"] != event["joint"]]
                self.extra.update(active=active, current=active[0] if active else None)
                self._ctx.set_phase("probing", progress=self.extra["done"] / max(self.extra["total"], 1))
                self._ctx.log(_describe(result))
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def finish(self, saved: str | None) -> None:
        with self._lock:
            self.extra.update(step="done", current=None, active=[], saved=saved)
            self._publish()


def _describe(r: dict) -> str:
    head = f"{r['joint']} {r['sense']} ({r['method']}"
    head += f", pass {r['run']}):" if r.get("run", 1) > 1 else "):"
    if r.get("skipped"):
        return f"{head} skipped — {r['skipped']}"
    if r["method"] == "takeup":
        tail = "stalled" if r.get("stalled") else "did not stall"
        return f"{head} {r['free_deg']:.1f}° free travel at {r['curve'][0][0]:.0f} mA, {tail}"
    if r["method"] == "stroke":
        mean = f"{r['mean_ma']:.0f} mA" if r.get("mean_ma") is not None else "no reading"
        tail = f", stalled after {r['free_deg']:.1f}°" if r.get("stalled") else ""
        return f"{head} {mean} over the stroke{tail}"
    brk = f"{r['breakaway_ma']:.0f} mA" if r.get("breakaway_ma") is not None else "none"
    mov = f"{r['move_ma']:.0f} mA" if r.get("move_ma") is not None else "none"
    return f"{head} breakaway {brk}, follows at {mov}"


def _save(
    ctx: OpContext, config, report: dict, params: dict, family: str | None = None
) -> str | None:
    from orca_ui.hand import baselines, probes
    from orca_ui.hand.operations.guided_tension import motor_family

    try:
        active = baselines.active_baseline(config)
        name = probes.save(
            config,
            params.get("name") or probes.dataset_name(config, "check" if report.get("check") else "probe"),
            report,
            hand_key=ctx.service.supervisor.hand_id,
            baseline=active[0] if active else None,
            note=params.get("note"),
            motor_type=family or motor_family(ctx.service),
        )
        ctx.log(f"saved as {name}")
        return name
    except Exception as e:
        ctx.log(f"probe dataset not saved: {e}")
        return None


def run_probe(ctx: OpContext, hand, params: dict, presenter: _Presenter, family: str | None) -> dict:
    """Run the probe ``params`` describe on an open maintenance hand, with the
    pose prompt first when asked for, and save the dataset. Returns the report
    (``saved`` added)."""
    check = params.get("ignore_calibration", False)
    if params.get("pose_prompt"):
        hand_ops.torque_off(hand)
        presenter.pose()
    report = hand_ops.tension_probe(
        hand,
        methods=params["methods"],
        joints=params.get("joints"),
        settings={**probe_defaults(ctx.service, family), **(params.get("settings") or {})},
        pose=params.get("pose", "mid"),
        repeats=params.get("repeats", DEFAULT_REPEATS),
        use_limits=not check,
        parallel=params.get("parallel", True),
        progress_callback=presenter.progress,
        should_stop=ctx.stop_event.is_set,
    )
    ctx.check_stop()
    report["check"] = check
    report["saved"] = _save(ctx, ctx.service.supervisor.config, report, params, family)
    presenter.finish(report["saved"])
    return report


# What guided tensioning runs between the range check and the ratchet: the
# stroke, so every motor of a group moves at the same instant.
CHECK_PARAMS = {
    "methods": ["stroke"],
    "repeats": 1,
    "pose": "hold",
    "ignore_calibration": True,
    "parallel": True,
    "pose_prompt": False,
}


class TensionProbeOperation(Operation):
    kind = "tension_probe"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_probe_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        check = self.params.get("ignore_calibration", False)
        presenter = _Presenter(ctx, self.params["methods"], check)
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config,
                ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None,
            )
            self._hand = hand
            # The session is torn down in maintenance, so the family comes from
            # the hand just opened, not from the (possibly unset) config.
            family = hand_family(hand)
            ctx.log(f"motor family: {family or 'unknown'}")
            report = run_probe(ctx, hand, self.params, presenter, family)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": report["saved"], "results": len(report["results"])}
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()


# ----- simulated (mock) ---------------------------------------------------------


class SimulatedTensionProbeOperation(Operation):
    """Plays the real event sequence with a synthetic spring-and-slack tendon per
    joint, so the dialog and the saved dataset can be exercised without a hand."""

    kind = "tension_probe"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.operations.simulated import _sim_step_duration

        clean = validate_probe_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        return clean

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        presenter = _Presenter(ctx, self.params["methods"], self.params.get("ignore_calibration", False))
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(self.params["step_duration_s"])
            report = simulate_probe(ctx, supervisor.config, self.params, presenter)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": report["saved"], "results": len(report["results"])}
        finally:
            supervisor.exit_maintenance()


def simulate_probe(ctx: OpContext, config, params: dict, presenter: _Presenter, slack: dict | None = None) -> dict:
    """Lease-free simulated probe with a synthetic spring-and-slack tendon per
    joint (``slack`` = free degrees per joint, random when omitted), the joints
    of one kind ramping together; the dataset is saved like the real one."""
    from orca_core.maintenance.tension_probe import probe_groups

    step_s = params["step_duration_s"]
    methods = params["methods"]
    settings = {**probe_defaults(ctx.service), **(params.get("settings") or {})}
    check = params.get("ignore_calibration", False)
    if params.get("pose_prompt"):
        presenter.pose()
    joints = [j for j in config.joint_ids if j != "wrist" and j in config.joint_to_motor_map]
    if params.get("joints") is not None:
        joints = [j for j in joints if j in set(params["joints"])]
    slack = {j: (slack or {}).get(j, random.uniform(0.0, 12.0)) for j in joints}
    repeats = int(params.get("repeats", DEFAULT_REPEATS))
    total = len(joints) * 2 * len(methods) * repeats
    presenter.progress({
        "event": "probe_plan", "joints": joints, "methods": methods, "pose": params.get("pose", "mid"),
        "total": total, "repeats": repeats, "centre_deg": {j: 180.0 for j in joints},
    })
    index = 0
    results = []
    groups = probe_groups(joints, params.get("parallel", True))
    for run in range(1, repeats + 1):
        for group in groups:
            for direction in (1, -1):
                sense = "flex" if direction == 1 else "extend"
                for method in methods:
                    ctx.check_stop()
                    batch = []
                    for joint in group:
                        motor = int(config.joint_to_motor_map[joint])
                        index += 1
                        meta = dict(joint=joint, motor=motor, direction=direction, sense=sense, method=method,
                                    index=index, total=total, run=run, group=list(group))
                        presenter.progress({"event": "probe_started", **meta})
                        free = slack[joint] * (1.0 if direction == 1 else 0.7)
                        result = dict(joint=joint, motor_id=motor, direction=direction, sense=sense, method=method,
                                      cap_deg=settings["max_travel_deg"], free_deg=None, stalled=None,
                                      breakaway_ma=None, move_ma=None, curve=[], duration_s=round(step_s, 3),
                                      skipped=None, run=run)
                        batch.append((meta, free, result))
                    reach = lambda free, ma: free + max(0.0, ma - 60.0) * 0.2  # noqa: E731
                    if method == "stroke":
                        # Everyone moves together; a slack tendon loads the motor less.
                        for k in range(1, 6):
                            for meta, free, result in batch:
                                presenter.progress({"event": "probe_sample", "current_ma": 60.0 - free * 3,
                                                    "deg": settings["max_travel_deg"] * k / 5, **meta})
                            ctx.sleep(step_s / 5)
                        for meta, free, result in batch:
                            level = round(max(5.0, 60.0 - free * 3), 1)
                            result.update(mean_ma=level, peak_ma=level + 5, breakaway_ma=level, free_deg=settings["max_travel_deg"],
                                          stalled=False, capped=True,
                                          curve=[[level, settings["max_travel_deg"] * k / 5] for k in range(1, 6)])
                    elif method == "takeup":
                        ma = settings["takeup_current_ma"]
                        for k in range(1, 4):
                            for meta, free, result in batch:
                                presenter.progress({"event": "probe_sample", "current_ma": ma,
                                                    "deg": reach(free, ma) * k / 3, **meta})
                            ctx.sleep(step_s / 3)
                        for meta, free, result in batch:
                            result.update(free_deg=round(reach(free, ma), 2), stalled=True,
                                          curve=[[ma, round(reach(free, ma), 2)]])
                    else:
                        ma = settings["start_current_ma"]
                        pending = list(batch)
                        while pending:
                            for meta, free, result in list(pending):
                                deg = min(reach(free, ma), settings["max_travel_deg"])
                                result["curve"].append([ma, round(deg, 2)])
                                presenter.progress({"event": "probe_sample", "current_ma": ma, "deg": deg, **meta})
                                if result["breakaway_ma"] is None and deg >= settings["play_deg"]:
                                    result["breakaway_ma"] = ma
                                if deg >= settings["move_deg"]:
                                    result["move_ma"] = ma
                                    pending.remove((meta, free, result))
                            if ma >= settings["max_current_ma"]:
                                break
                            ma = min(ma + settings["step_current_ma"], settings["max_current_ma"])
                            ctx.sleep(step_s / 6)
                    for meta, free, result in batch:
                        results.append(result)
                        presenter.progress({"event": "probe_done", "result": result, **meta})
    report = {
        "centre_deg": {j: 180.0 for j in joints}, "results": results, "settings": settings,
        "methods": methods, "joints": joints, "repeats": repeats, "check": check,
        "parallel": params.get("parallel", True),
    }
    report["saved"] = _save(ctx, config, report, params)
    presenter.finish(report["saved"])
    return report

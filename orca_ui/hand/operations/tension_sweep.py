"""Tension sweep operation: measure the current every motor needs over its
joint's whole travel, and compare it with the reference hand.

Runs orca_core's run_tension_sweep under the maintenance lease on a calibrated
hand, one joint at a time with the others holding, ``repeats`` passes limit to
limit and back. The dataset is saved beside the calibration as GT_sweep_NN;
the reference sweep (a hand tensioned right) is what later sweeps are scored
against. Live samples stream through the snapshot ``extra`` (TensionSweepExtra).
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

logger = logging.getLogger(__name__)

DEFAULT_REPEATS = 1
MAX_REPEATS = 5
PUBLISH_PERIOD_S = 0.1
FAMILY_CURRENT_SCALE = {"feetech": 2.0}
SETTING_BOUNDS = {
    "hold_current_ma": (20.0, 500.0),
    "pose_current_ma": (20.0, 600.0),
    "sweep_current_ma": (50.0, 600.0),
    "speed_deg_s": (5.0, 90.0),
    "limit_margin_deg": (0.0, 20.0),
    "deadband_ma": (0.0, 200.0),
}


def validate_sweep_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError
    from orca_ui.hand.operations.tension_probe import _current_ceiling

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — the sweep needs motors", status_code=409)
    if not hand_ops.tension_sweep_supported():
        raise ServiceError("the installed orca_core has no tension sweep", status_code=409)
    clean: dict = {}
    repeats = params.get("repeats", DEFAULT_REPEATS)
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= MAX_REPEATS:
        raise ServiceError(f"repeats must be an integer from 1 to {MAX_REPEATS}", status_code=422)
    clean["repeats"] = repeats
    config = service.supervisor.config
    joints = params.get("joints")
    if joints is not None:
        known = set(config.joint_ids) - {"wrist"}
        if not isinstance(joints, list) or not joints or not set(joints) <= known:
            raise ServiceError("joints must be a non-empty list of this hand's finger joints", status_code=422)
        clean["joints"] = list(joints)
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
            raise ServiceError(f"{key} must be between {low:g} and {high:g}", status_code=422)
        settings[key] = value
    clean["settings"] = settings
    name = params.get("name")
    if name is not None:
        from orca_ui.hand.sweeps import NAME_RE

        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ServiceError("name: 1-40 letters, digits, _ . -", status_code=422)
        clean["name"] = name
    note = params.get("note")
    if note is not None:
        clean["note"] = str(note)[:200]
    return clean


def sweep_defaults(service, family: str | None = None) -> dict:
    """SweepSettings defaults for the motor family, currents scaled like the probe's."""
    from orca_ui.hand.operations.guided_tension import motor_family
    from orca_ui.hand.operations.tension_probe import _current_ceiling

    defaults = hand_ops.sweep_setting_defaults()
    scale = FAMILY_CURRENT_SCALE.get(family or motor_family(service) or "", 1.0)
    ceiling = _current_ceiling(service.supervisor.config, service.session)
    for key in list(defaults):
        if not key.endswith("_ma") or key == "deadband_ma":
            continue
        value = defaults[key] * scale
        lo, hi = SETTING_BOUNDS.get(key, (0.0, value))
        if ceiling is not None:
            hi = min(hi, ceiling)
        defaults[key] = float(max(lo, min(value, hi)))
    return defaults


class _Presenter:
    def __init__(self, ctx: OpContext, reference: tuple[str, dict] | None):
        self._ctx = ctx
        self._lock = threading.Lock()
        self._last = 0.0
        self._reference = reference
        # Every result with its curve, for scoring; the snapshot carries them without.
        self._full: list[dict] = []
        self.extra: dict = {
            "step": "starting",
            "index": 0,
            "done": 0,
            "total": 0,
            "repeats": 1,
            "joints": [],
            "groups": [],
            "travel_deg": {},
            "current": None,
            "active": [],
            "results": [],
            "reference": reference[0] if reference else None,
            "verdict": None,
        }

    def _publish(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last < PUBLISH_PERIOD_S:
            return
        self._last = now
        self._ctx.set_extra({**self.extra, "results": list(self.extra["results"]), "active": list(self.extra["active"])})

    def _rescore(self) -> None:
        from orca_ui.hand import sweeps

        self.extra["verdict"] = sweeps.compare(self._full, self._reference[1] if self._reference else None)

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "pose_short":
                self.extra["pose_short"] = dict(event["joints"])
                off = ", ".join(f"{j} ({d:g}°)" for j, d in event["joints"].items())
                self._ctx.log(f"mid-range pose not reached on {off}")
            elif kind == "sweep_plan":
                self.extra.update(step="sweeping", total=event["total"], repeats=int(event.get("repeats", 1)),
                                  joints=event["joints"], travel_deg=event["travel_deg"],
                                  groups=event.get("groups") or [[j] for j in event["joints"]])
                self._ctx.log(
                    f"sweeping {len(event['joints'])} joints limit to limit and back"
                    + (f" × {event['repeats']} passes" if event.get("repeats", 1) > 1 else "")
                    + f", {len(self.extra['groups'])} groups"
                )
                self._publish()
            elif kind == "sweep_started":
                entry = {k: event[k] for k in ("joint", "motor", "direction", "sense", "run")} | {
                    "deg": None, "current_ma": None, "index": event["index"]}
                active = [a for a in self.extra["active"] if a["joint"] != event["joint"]] + [entry]
                self.extra.update(index=event["index"], active=active, current=active[0])
                passes = f"pass {event['run']}/{self.extra['repeats']} · " if self.extra["repeats"] > 1 else ""
                names = ", ".join(a["joint"] for a in active)
                self._ctx.set_phase("sweeping", progress=self.extra["done"] / max(event["total"], 1),
                                    detail=f"{passes}{names} {event['sense']}")
                self._publish()
            elif kind == "sweep_sample":
                for a in self.extra["active"]:
                    if a["joint"] == event["joint"]:
                        a.update(deg=event["deg"], current_ma=event["current_ma"])
                self._publish(force=False)
            elif kind == "sweep_done":
                result = event["result"]
                self._full.append(result)
                if isinstance(result.get("samples"), list):
                    result = {**result, "samples": len(result["samples"])}
                self.extra["results"] = self.extra["results"] + [result]
                self.extra["done"] = len(self.extra["results"])
                active = [a for a in self.extra["active"] if a["joint"] != result["joint"]]
                self.extra.update(active=active, current=active[0] if active else None)
                self._ctx.set_phase("sweeping", progress=self.extra["done"] / max(self.extra["total"], 1))
                self._rescore()
                self._ctx.log(_describe(result))
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def finish(self, saved: str | None) -> None:
        with self._lock:
            self.extra.update(step="done", current=None, active=[], saved=saved)
            self._rescore()
            self._publish()


def _describe(r: dict) -> str:
    head = f"{r['joint']} {r['sense']}" + (f" (pass {r['run']})" if r.get("run", 1) > 1 else "")
    if r.get("skipped"):
        return f"{head}: skipped — {r['skipped']}"
    short = f", stalled {r['short_deg']:.0f}° short of the limit" if (r.get("short_deg") or 0) > 2 else ""
    return (
        f"{head}: {r['mean_ma']:.0f} mA over the travel, {r['end_ma']:.0f} mA into the stop, "
        f"dead band {r['deadband_deg']:.1f}°{short}"
    )


def _save(ctx: OpContext, config, report: dict, params: dict, family: str | None) -> str | None:
    from orca_ui.hand import sweeps
    from orca_ui.hand.operations.guided_tension import motor_family

    try:
        name = sweeps.save(config, params.get("name"), report, hand_key=ctx.service.supervisor.hand_id,
                           note=params.get("note"), motor_type=family or motor_family(ctx.service))
        ctx.log(f"saved as {name}")
        return name
    except Exception as e:
        ctx.log(f"sweep dataset not saved: {e}")
        return None


class TensionSweepOperation(Operation):
    kind = "tension_sweep"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_sweep_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand import sweeps
        from orca_ui.hand.operations.tension_probe import hand_family

        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        presenter = _Presenter(ctx, sweeps.reference(supervisor.config))
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None,
            )
            self._hand = hand
            family = hand_family(hand)
            ctx.log(f"motor family: {family or 'unknown'}")
            report = hand_ops.tension_sweep(
                hand,
                joints=self.params.get("joints"),
                settings={**sweep_defaults(ctx.service, family), **(self.params.get("settings") or {})},
                repeats=self.params.get("repeats", DEFAULT_REPEATS),
                progress_callback=presenter.progress,
                should_stop=ctx.stop_event.is_set,
            )
            ctx.check_stop()
            saved = _save(ctx, supervisor.config, report, self.params, family)
            presenter.finish(saved)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": saved, "results": len(report["results"])}
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()


# ----- simulated (mock) ---------------------------------------------------------


class SimulatedTensionSweepOperation(Operation):
    """Plays the real event sequence with a synthetic load curve per joint, so
    the dialog, the dataset and the comparison can be exercised without a hand."""

    kind = "tension_sweep"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.operations.simulated import _sim_step_duration

        clean = validate_sweep_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        # Per-joint load scale a test may script, e.g. {"index_pip": 0.5} for a loose tendon.
        scale = params.get("load_scale") or {}
        clean["load_scale"] = {str(j): float(v) for j, v in scale.items()} if isinstance(scale, dict) else {}
        return clean

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand import sweeps

        supervisor = ctx.service.supervisor
        config = supervisor.config
        step_s = self.params["step_duration_s"]
        settings = {**sweep_defaults(ctx.service), **(self.params.get("settings") or {})}
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        presenter = _Presenter(ctx, sweeps.reference(config))
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(step_s)
            joints = [j for j in config.joint_ids if j != "wrist" and j in config.joint_to_motor_map]
            if self.params.get("joints") is not None:
                joints = [j for j in joints if j in set(self.params["joints"])]
            repeats = int(self.params.get("repeats", DEFAULT_REPEATS))
            travel = {j: 100.0 for j in joints}
            total = len(joints) * 2 * repeats
            from orca_core.maintenance.tension_probe import probe_groups

            presenter.progress({"event": "sweep_plan", "joints": joints, "total": total,
                                "repeats": repeats, "travel_deg": travel, "groups": probe_groups(joints)})
            index = 0
            results = []
            rng = random.Random(7)
            for joint in joints:
                motor = int(config.joint_to_motor_map[joint])
                load = 100.0 * self.params["load_scale"].get(joint, 1.0)
                dead = 2.0 if self.params["load_scale"].get(joint, 1.0) >= 0.9 else 15.0
                for run in range(1, repeats + 1):
                    for direction in (1, -1):
                        ctx.check_stop()
                        index += 1
                        sense = "flex" if direction == 1 else "extend"
                        meta = dict(joint=joint, motor=motor, direction=direction, sense=sense,
                                    run=run, index=index, total=total)
                        presenter.progress({"event": "sweep_started", **meta})
                        samples = []
                        n = 20
                        for k in range(n + 1):
                            frac = k / n
                            deg = frac * 96.0 + 2.0 if direction > 0 else 98.0 - frac * 96.0
                            moved = frac * 96.0
                            ma = (load + 30.0 * frac + rng.uniform(-5, 5)) if moved >= dead else 4.0
                            samples.append([round(deg, 2), round(ma * direction, 1)])
                            presenter.progress({"event": "sweep_sample", "deg": deg, "current_ma": ma, **meta})
                            ctx.sleep(step_s / n)
                        from orca_core.maintenance.tension_sweep import summarize

                        result = dict(joint=joint, motor_id=motor, direction=direction, sense=sense, run=run,
                                      travel_deg=100.0, start_deg=2.0 if direction > 0 else 98.0,
                                      end_deg=98.0 if direction > 0 else 2.0, short_deg=0.0,
                                      samples=samples, duration_s=round(step_s, 3), skipped=None)
                        result.update(summarize(samples, direction, 100.0, settings["deadband_ma"], result["start_deg"]))
                        results.append(result)
                        presenter.progress({"event": "sweep_done", "result": dict(result), **meta})
            report = {"joints": joints, "limits_deg": {j: [0.0, 100.0] for j in joints}, "travel_deg": travel,
                      "results": results, "settings": settings, "repeats": repeats}
            saved = _save(ctx, config, report, self.params, None)
            presenter.finish(saved)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": saved, "results": len(results)}
        finally:
            supervisor.exit_maintenance()

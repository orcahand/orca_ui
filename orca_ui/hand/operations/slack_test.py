"""Slack test operation: wind every finger motor half a turn each way at a
current too low to move a tensioned joint, and read the slack off how far each
one got.

Runs orca_core's run_slack_test under the maintenance lease. The report is
kept beside the hand's calibration (slack_tests.yaml); a motor that completed
the half turn blocks calibration until the hand is tensioned and tested again.
Live angles stream through the snapshot ``extra`` (SlackTestExtra).
"""

from __future__ import annotations

import logging
import random
import threading
import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

logger = logging.getLogger(__name__)

PUBLISH_PERIOD_S = 0.1
SETTING_BOUNDS = {
    "current_ma": (5.0, 100.0),
    "max_turn_deg": (30.0, 180.0),
    "slack_tolerance_deg": (0.0, 90.0),
}


def validate_slack_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — the slack test needs motors", status_code=409)
    if not hand_ops.slack_test_supported():
        raise ServiceError("the installed orca_core has no slack test", status_code=409)
    clean: dict = {}
    config = service.supervisor.config
    joints = params.get("joints")
    if joints is not None:
        known = set(config.joint_ids) - {"wrist"}
        if not isinstance(joints, list) or not joints or not set(joints) <= known:
            raise ServiceError("joints must be a non-empty list of this hand's finger joints", status_code=422)
        clean["joints"] = list(joints)
    settings = {}
    for key, (low, high) in SETTING_BOUNDS.items():
        if params.get(key) is None:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            raise ServiceError(f"{key} must be a number", status_code=422)
        if not low <= value <= high:
            raise ServiceError(f"{key} must be between {low:g} and {high:g}", status_code=422)
        settings[key] = value
    clean["settings"] = settings
    return clean


class _Presenter:
    def __init__(self, ctx: OpContext):
        self._ctx = ctx
        self._lock = threading.Lock()
        self._last = 0.0
        self.extra: dict = {
            "step": "starting",
            "direction": None,
            "joints": [],
            "live": {},
            "results": {},
            "blocked": False,
        }

    def _publish(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last < PUBLISH_PERIOD_S:
            return
        self._last = now
        self._ctx.set_extra({**self.extra, "live": dict(self.extra["live"]), "results": dict(self.extra["results"])})

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "slack_plan":
                self.extra.update(step="testing", joints=event["joints"])
                self.extra["results"] = {
                    j: {"motor": m, "plus_deg": None, "minus_deg": None, "status": None}
                    for j, m in zip(event["joints"], event["motors"])
                }
                self._ctx.log(f"slack test on {len(event['joints'])} motors, both directions")
                self._publish()
            elif kind == "slack_phase":
                self.extra.update(direction=event["direction"], live={})
                self._ctx.set_phase(
                    "testing",
                    progress=0.0 if event["direction"] > 0 else 0.5,
                    detail=f"winding {'positive' if event['direction'] > 0 else 'negative'} at low current",
                )
                self._publish()
            elif kind == "slack_sample":
                self.extra["live"] = dict(event["deg"])
                self._publish(force=False)
            elif kind == "slack_phase_done":
                key = "plus_deg" if event["direction"] > 0 else "minus_deg"
                for joint, deg in event["deg"].items():
                    row = self.extra["results"].setdefault(joint, {})
                    row[key] = deg
                    row[key.replace("_deg", "_capped")] = bool(event["capped"].get(joint))
                capped = [j for j, c in event["capped"].items() if c]
                moved = [f"{j} {d:.0f}°" for j, d in event["deg"].items() if d >= 1.0 and j not in capped]
                self._ctx.log(
                    f"{'positive' if event['direction'] > 0 else 'negative'}: "
                    + (", ".join(moved) if moved else "nothing turned")
                    + (f"; half a turn on {', '.join(capped)}" if capped else "")
                )
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def finish(self, report: dict, saved: str | None) -> None:
        with self._lock:
            for r in report["results"]:
                self.extra["results"][r["joint"]] = {
                    "motor": r["motor_id"],
                    "plus_deg": r["plus_deg"],
                    "minus_deg": r["minus_deg"],
                    "plus_capped": r["plus_capped"],
                    "minus_capped": r["minus_capped"],
                    "plus_sense": r["plus_sense"],
                    "minus_sense": r["minus_sense"],
                    "total_deg": r["total_deg"],
                    "status": r["status"],
                }
            self.extra.update(step="done", direction=None, live={}, blocked=report["blocked"],
                              settings=report["settings"], saved=saved)
            self._publish()


def _save(ctx: OpContext, config, report: dict, family: str | None) -> str | None:
    from orca_ui.hand import slack_tests
    from orca_ui.hand.operations.guided_tension import motor_family

    try:
        key = slack_tests.save(config, report, hand_key=ctx.service.supervisor.hand_id,
                               motor_type=family or motor_family(ctx.service))
        ctx.log("slack test saved" + (" — calibration is blocked until a passing test" if report["blocked"] else ""))
        return key
    except Exception as e:
        ctx.log(f"slack test not saved: {e}")
        return None


class SlackTestOperation(Operation):
    kind = "slack_test"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_slack_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.operations.tension_probe import hand_family

        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        presenter = _Presenter(ctx)
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None,
            )
            self._hand = hand
            family = hand_family(hand)
            report = hand_ops.slack_test(
                hand,
                joints=self.params.get("joints"),
                settings=self.params.get("settings") or {},
                progress_callback=presenter.progress,
                should_stop=ctx.stop_event.is_set,
            )
            ctx.check_stop()
            saved = _save(ctx, supervisor.config, report, family)
            presenter.finish(report, saved)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": saved, "blocked": report["blocked"],
                    "slack": {r["joint"]: r["status"] for r in report["results"]}}
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()


# ----- simulated (mock) ---------------------------------------------------------


class SimulatedSlackTestOperation(Operation):
    """Plays the real event sequence with a synthetic slack per spool; a joint
    named in ``params["unspool"]`` turns the whole half turn."""

    kind = "slack_test"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.operations.simulated import _sim_step_duration

        clean = validate_slack_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        unspool = params.get("unspool") or []
        clean["unspool"] = [str(j) for j in unspool] if isinstance(unspool, list) else []
        return clean

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.operations.simulated import simulate_slack_test

        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        presenter = _Presenter(ctx)
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(self.params["step_duration_s"])
            report = simulate_slack_test(ctx, supervisor.config, self.params, presenter.progress)
            saved = _save(ctx, supervisor.config, report, None)
            presenter.finish(report, saved)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": saved, "blocked": report["blocked"],
                    "slack": {r["joint"]: r["status"] for r in report["results"]}}
        finally:
            supervisor.exit_maintenance()

"""Slack test operation: the operator holds one finger joint at a time while
its motor winds each way at low current; the free rotation is the slack.

Runs orca_core's run_slack_test under the maintenance lease, asking for each
joint through ``ctx.wait_input`` (hold, then Test, Skip, or Back to test the
previous joint again). The report is kept
in the hand's setup.yaml (slack_tests); a joint with more than half
a turn of slack blocks calibration until the hand is tensioned and tested
again. Live angles stream through the snapshot ``extra`` (SlackTestExtra).
"""

from __future__ import annotations

import logging
import threading
import time

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

logger = logging.getLogger(__name__)

PUBLISH_PERIOD_S = 0.1
SETTING_BOUNDS = {
    "current_ma": (20.0, 150.0),
    "max_free_deg": (30.0, 180.0),
}
HOLD_TEST = "Test"
HOLD_SKIP = "Skip"
HOLD_BACK = "Back"


def hold_prompt(joint: str) -> str:
    return f"Hold {joint.replace('_', ' ')} still so the joint cannot move, then test"


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
            "joint": None,
            "direction": None,
            "joints": [],
            "live": None,
            "results": {},
            "blocked": False,
            "can_back": False,
        }

    def _publish(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last < PUBLISH_PERIOD_S:
            return
        self._last = now
        self._ctx.set_extra({**self.extra, "results": dict(self.extra["results"])})

    def hold(self, joint: str) -> bool | str:
        """Park on the hold prompt for ``joint``; False when the operator skips
        it, orca_core's HOLD_BACK to test the previous joint again."""
        from orca_core.maintenance.slack_test import HOLD_BACK as CORE_BACK

        with self._lock:
            can_back = self.extra["joints"].index(joint) > 0
            self.extra.update(step="hold", joint=joint, direction=None, live=None, can_back=can_back)
            self._publish()
        self._ctx.set_phase("hold", detail=f"torque off — hold {joint.replace('_', ' ')}")
        options = [HOLD_TEST, HOLD_SKIP] + ([HOLD_BACK] if can_back else [])
        answer = self._ctx.wait_input(hold_prompt(joint), options)
        return {HOLD_SKIP: False, HOLD_BACK: CORE_BACK}.get(answer, True)

    def progress(self, event: dict) -> None:
        kind = event.get("event")
        with self._lock:
            if kind == "slack_plan":
                self.extra.update(step="testing", joints=event["joints"])
                self.extra["results"] = {
                    j: {"motor": m, "plus_deg": None, "minus_deg": None, "status": None}
                    for j, m in zip(event["joints"], event["motors"])
                }
                self._ctx.log(f"slack test on {len(event['joints'])} joints, one at a time, joint held")
                self._publish()
            elif kind == "slack_joint":
                total = len(self.extra["joints"]) or 1
                self._ctx.set_progress(event["index"] / total)
            elif kind == "slack_phase":
                self.extra.update(step="testing", joint=event["joint"], direction=event["direction"], live=0.0)
                self._ctx.set_phase(
                    "testing",
                    detail=f"{event['joint'].replace('_', ' ')}: winding toward {event['sense']}",
                )
                self._publish()
            elif kind == "slack_sample":
                self.extra["live"] = event["deg"]
                self._publish(force=False)
            elif kind == "slack_joint_done":
                r = event["result"]
                self.extra["results"][r["joint"]] = _row(r, self._ctx.service.supervisor.config)
                self.extra.update(direction=None, live=None)
                self._ctx.log(
                    f"{r['joint']}: skipped" if r["status"] == "skipped"
                    else f"{r['joint']}: {r['total_deg']:.0f}° free ({r['plus_deg']:.0f} + {r['minus_deg']:.0f})"
                    + (" — too slack" if r["status"] == "fail" else "")
                )
                self._publish()
            elif kind == "slack_joint_back":
                joint = event["joint"]
                self.extra["results"][joint] = {
                    **self.extra["results"][joint],
                    "plus_deg": None, "minus_deg": None, "total_deg": None, "clicks": None, "status": None,
                }
                self._ctx.log(f"{joint}: back — testing it again")
                self._publish()
            elif kind == "cleanup_failed":
                self._ctx.log(f"cleanup failed: {event.get('error')}")

    def finish(self, report: dict, saved: str | None) -> None:
        with self._lock:
            for r in report["results"]:
                self.extra["results"][r["joint"]] = _row(r, self._ctx.service.supervisor.config)
            self.extra.update(step="done", joint=None, direction=None, live=None, blocked=report["blocked"],
                              settings=report["settings"], saved=saved, deg_per_click=_deg_per_click())
            self._publish()


def _row(r: dict, config) -> dict:
    from orca_ui.hand import reference

    skipped = r["status"] == "skipped"
    return {
        "clicks": None if skipped else reference.clicks_for_slack(r["total_deg"], r["joint"]),
        "ref_deg": reference.slack(config, None).get(r["joint"]),
        "motor": r["motor_id"],
        "plus_deg": r["plus_deg"],
        "minus_deg": r["minus_deg"],
        "plus_sense": r["plus_sense"],
        "minus_sense": r["minus_sense"],
        "total_deg": r["total_deg"],
        "status": r["status"],
    }


def _deg_per_click() -> float | None:
    from orca_ui.hand import reference

    return reference.deg_per_click()


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
            family = hand_ops.hand_family(hand)
            report = hand_ops.slack_test(
                hand,
                joints=self.params.get("joints"),
                settings=self.params.get("settings") or {},
                hold_callback=presenter.hold,
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
    """Plays the real event sequence, hold prompts included, with a synthetic
    slack per spool; a joint named in ``params["unspool"]`` turns past half a turn."""

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
            report = simulate_slack_test(ctx, supervisor.config, self.params, presenter.hold, presenter.progress)
            saved = _save(ctx, supervisor.config, report, None)
            presenter.finish(report, saved)
            ctx.set_phase("released", detail="torque off, control mode restored")
            return {"saved": saved, "blocked": report["blocked"],
                    "slack": {r["joint"]: r["status"] for r in report["results"]}}
        finally:
            supervisor.exit_maintenance()

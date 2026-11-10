"""Checks that run inside the console, against its live session and its own
operations.

Checks that move the hand go through the console's own gates: operations
start through the operation manager (which refuses unless manual control owns
the hand), and direct actions call ``require_manual_control`` first. A check
that cannot verify part of its pass rule with what the console offers says so
in its summary instead of guessing.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from orca_ui.hardware_tests.checks.base import CheckContext, StopRequested, register
from orca_ui.hardware_tests.model import CheckResult, Metric, Series

POLL_S = 0.2
OPERATION_TIMEOUT_S = 1800.0
RECONNECT_TIMEOUT_S = 60.0
STOP_GRACE_S = 30.0
MOCK_STEP_S = 0.05
"""Simulated operations' step duration in mock mode, so a check finishes in seconds."""
CLOCK_SLACK = timedelta(seconds=2)
"""Saved records carry whole-second timestamps."""
SLACK_BACK_SUFFIX = ": back — testing it again"


# ----- helpers ---------------------------------------------------------------------


def hardware_version_source(service, status: Optional[dict] = None) -> Optional[str]:
    """Where the version in force came from: ``picker`` (local_config.yaml
    beside the hand's config), ``pin`` (config.yaml), ``board``, or None."""
    status = status or service.status()
    version = status.get("hardware_version")
    if version is None:
        return None
    if status.get("hardware_version_pinned"):
        from orca_core.constants import HARDWARE_VERSION
        from orca_core.hand_config import read_local_config

        try:
            local = read_local_config(service.supervisor.config.config_path)
        except Exception:
            local = {}
        return "picker" if local.get(HARDWARE_VERSION) is not None else "pin"
    if status.get("board_hardware_version") == version:
        return "board"
    return None


def _parse_time(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(str(text).rstrip("+"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _step_started(ctx: CheckContext) -> Optional[datetime]:
    own = ctx.step_result(ctx.step.id) or {}
    return _parse_time(own.get("started_at"))


def _is_new(recorded: Optional[str], since: Optional[datetime]) -> bool:
    when = _parse_time(recorded)
    return when is not None and (since is None or when >= since - CLOCK_SLACK)


def _wait(ctx: CheckContext, seconds: float) -> None:
    wait = getattr(ctx, "wait", None)
    if wait is not None:
        wait(seconds)
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ctx.check_stop()
        time.sleep(min(POLL_S, max(0.0, deadline - time.monotonic())))


def _step_events(ctx: CheckContext, step_id: str) -> list[dict]:
    reader = getattr(ctx, "step_events", None)
    return reader(step_id) if reader is not None else []


def _step_operations(ctx: CheckContext, step_id: str) -> list[dict]:
    reader = getattr(ctx, "step_operations", None)
    return reader(step_id) if reader is not None else []


def _finger_joints(config, absent: set) -> list[str]:
    return [j for j in config.joint_ids
            if j != "wrist" and j in config.joint_to_motor_map and j not in absent]


def _absent_joints(service) -> set:
    session = service.session
    return set(getattr(getattr(session, "hand", None), "absent_joints", []) or [])


def _family(service) -> Optional[str]:
    from orca_ui.hand.operations.guided_tension import motor_family

    return motor_family(service)


def _wait_connected(ctx: CheckContext, timeout_s: float = RECONNECT_TIMEOUT_S) -> None:
    """Block until the console has a live session again (after a maintenance lease)."""
    deadline = time.monotonic() + timeout_s
    while True:
        status = ctx.service.status()
        if ctx.service.session is not None and status.get("state") in ("connected", "degraded"):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"the hand did not reconnect within {timeout_s:g} s "
                               f"(state {status.get('state')}: {status.get('message')})")
        _wait(ctx, POLL_S)


def _await_terminal(manager, run_id: str, timeout_s: float) -> Optional[dict]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = manager.snapshot()
        if snapshot is None or snapshot.get("run_id") != run_id or snapshot.get("state") in ("done", "error"):
            return snapshot
        time.sleep(POLL_S)
    return manager.snapshot()


def _run_operation(ctx: CheckContext, kind: str, params: dict,
                   timeout_s: float = OPERATION_TIMEOUT_S) -> dict:
    """Start a console operation, follow it to the end and return its last
    snapshot. Stop stops the operation too. An operation that asks for input
    is stopped: a check runs unattended."""
    manager = ctx.service.operation_manager
    if manager is None:
        raise RuntimeError("the console has no operation manager")
    if ctx.settings.mock:
        params = {**params, "step_duration_s": MOCK_STEP_S}
    snapshot = manager.start(kind, params)
    run_id = snapshot.get("run_id")
    ctx.log(f"started {kind} ({run_id})")
    deadline = time.monotonic() + timeout_s
    while True:
        snapshot = manager.snapshot() or {}
        if snapshot.get("run_id") != run_id:
            raise RuntimeError(f"{kind} was replaced by another operation")
        state = snapshot.get("state")
        if state in ("done", "error"):
            ctx.log(f"{kind} ended: {state}" + (f" — {snapshot.get('error')}" if snapshot.get("error") else ""))
            return snapshot
        if state == "awaiting_input":
            manager.stop()
            _await_terminal(manager, run_id, STOP_GRACE_S)
            prompt = (snapshot.get("awaiting") or {}).get("prompt")
            raise RuntimeError(f"{kind} asked for input ({prompt!r}) and a check cannot answer it")
        if time.monotonic() >= deadline:
            manager.stop()
            _await_terminal(manager, run_id, STOP_GRACE_S)
            raise TimeoutError(f"{kind} did not finish within {timeout_s:g} s")
        try:
            _wait(ctx, POLL_S)
        except StopRequested:
            manager.stop()
            _await_terminal(manager, run_id, STOP_GRACE_S)
            raise


def _service_error():
    from orca_ui.hand.service import ServiceError

    return ServiceError


def _no_hand(ctx: CheckContext) -> Optional[CheckResult]:
    session = ctx.service.session
    if session is None:
        return CheckResult(status="error", summary="the hand is not connected to the console")
    if not session.caps.motors:
        return CheckResult(status="error", summary="the console's session has no motor bus")
    return None


def _busy(ctx: CheckContext) -> Optional[CheckResult]:
    manager = ctx.service.operation_manager
    if manager is not None and manager.active():
        snapshot = manager.snapshot() or {}
        return CheckResult(status="error",
                           summary=f"operation {snapshot.get('kind')!r} is running — stop it and run the check again")
    try:
        ctx.service.require_manual_control()
    except _service_error() as e:
        return CheckResult(status="error", summary=str(e))
    return None


def _sweep_rows(results: list[dict]) -> list[dict]:
    keys = ("joint", "sense", "run", "travel_deg", "start_deg", "end_deg", "short_deg", "mean_ma",
            "end_ma", "peak_ma", "deadband_deg", "duration_s", "skipped")
    return [{k: r.get(k) for k in keys} for r in results]


# ----- slack test ------------------------------------------------------------------


def _readings(test: dict) -> int:
    return sum(1 for r in test.get("results") or []
               if r.get("status") not in (None, "skipped") and r.get("total_deg") is not None)


@register("slack_test_saved")
def slack_test_saved(ctx: CheckContext) -> CheckResult:
    """A1: a slack test saved during the step covers every joint at the family's
    default current, and Back retested a joint (possibly in another run of the step)."""
    from orca_ui.hand import slack_tests
    from orca_ui.hand.operations import hand_ops

    service = ctx.service
    config = service.supervisor.config
    since = _step_started(ctx)
    saved = slack_tests.for_hand(config, service.supervisor.hand_id)
    if not saved:
        return CheckResult(status="fail", summary="no slack test is saved beside the calibration (setup.yaml slack_tests)")
    during = [kv for kv in saved if _is_new(kv[1].get("recorded_at"), since)]
    # The fullest run decides coverage, so a short run made only to try Back doesn't hide it.
    key, test = max(during or saved, key=lambda kv: (_readings(kv[1]), kv[1].get("recorded_at", ""), kv[0]))
    problems: list[str] = []
    unverified: list[str] = []
    new = bool(during)
    if not new:
        problems.append(f"the newest saved slack test ({key}) is older than this step")

    results = test.get("results") or []
    tested = [r.get("joint") for r in results]
    expected = _finger_joints(config, _absent_joints(service))
    missing = [j for j in expected if j not in tested]
    no_reading = [r.get("joint") for r in results if r.get("status") in (None, "skipped") or r.get("total_deg") is None]
    if missing:
        problems.append(f"not in the saved test: {', '.join(missing)}")
    if no_reading:
        problems.append(f"no reading for {', '.join(no_reading)}")

    family = test.get("motor_type") or _family(service)
    default_ma = hand_ops.slack_setting_defaults(family)["current_ma"] if family else None
    used_ma = (test.get("settings") or {}).get("current_ma")
    current_ok = None
    if default_ma is None or used_ma is None:
        unverified.append("the winding current (motor family or saved current unknown)")
    else:
        current_ok = abs(float(used_ma) - float(default_ma)) < 0.5
        if not current_ok:
            problems.append(f"wound at {float(used_ma):g} mA, the {family} default is {float(default_ma):g} mA")

    lines = [e.get("line") or "" for e in _step_events(ctx, ctx.step.id) if e.get("type") == "operation_log"]
    backed: list[str] = []
    retested: list[str] = []
    for index, line in enumerate(lines):
        if line.endswith(SLACK_BACK_SUFFIX):
            joint = line[: -len(SLACK_BACK_SUFFIX)]
            backed.append(joint)
            # A reading reads "<joint>: 3° free (1 + 2)"; a skip after Back is not a retest.
            if joint not in retested and any(later.startswith(f"{joint}: ") and " free " in later
                                             for later in lines[index + 1:]):
                retested.append(joint)
    if not lines:
        unverified.append("Back (no operation log was recorded while the step was open)")
    elif not backed:
        problems.append("no Back was recorded in the operation log")
    elif not retested:
        problems.append(f"Back on {', '.join(backed)} was not followed by a new reading")

    metrics = [
        Metric("joints with a reading", len(results) - len(no_reading), unit=f"of {len(expected)}",
               ok=not missing and not no_reading),
        Metric("winding current", used_ma, unit="mA", ok=current_ok),
        Metric(f"{family or 'family'} default current", default_ma, unit="mA"),
        Metric("saved during this step", len(during), unit="tests", ok=new),
        Metric("Back retested", ", ".join(retested) or ("—" if lines else "not recorded"),
               ok=bool(retested) if lines else None),
        Metric("blocks calibration", "yes" if test.get("blocked") else "no"),
    ]
    tail = f" Not verified: {'; '.join(unverified)}." if unverified else ""
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + tail, metrics=metrics,
                           details={"slack_test": key, "results": results})
    return CheckResult(status="pass", summary=f"slack test {key} saved with a reading for all {len(expected)} joints "
                       f"at the family default current.{tail}", metrics=metrics,
                       details={"slack_test": key, "results": results})


def _routine_refuses_first(fn) -> bool:
    """True when the routine's first statement is the joint-loop guard, so
    calling it on a hand with a running loop cannot reach the motors."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    if not body or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Call):
        return False
    func = body[0].value.func
    return isinstance(func, ast.Attribute) and func.attr == "_refuse_routine_while_loop_runs"


@register("refused_while_joint_loop")
def refused_while_joint_loop(ctx: CheckContext) -> CheckResult:
    """A2: with the console's joint loop running, orca_core's slack test and
    tension sweep refuse before touching a motor; without a loop they start."""
    import types

    from orca_ui.hand.operations.slack_test import validate_slack_params
    from orca_ui.hand.operations.tension_sweep import validate_sweep_params

    blocked = _no_hand(ctx) or _busy(ctx)
    if blocked:
        return blocked
    session = ctx.service.session
    if not session.caps.feedback_loop:
        return CheckResult(status="skipped", summary="the console's session runs no joint-feedback loop "
                           "(the console was started with --no-feedback, or the loop did not engage)")
    try:
        from orca_core.maintenance.slack_test import run_slack_test
        from orca_core.maintenance.tension_sweep import run_tension_sweep
    except ImportError as e:
        return CheckResult(status="error", summary=f"the installed orca_core lacks a routine: {e}")

    hand = session.hand
    routines = {
        "slack test": (run_slack_test, {"hold_callback": lambda joint: False, "should_stop": lambda: True},
                       validate_slack_params),
        "tension sweep": (run_tension_sweep, {"should_stop": lambda: True}, validate_sweep_params),
    }
    metrics: list[Metric] = []
    problems: list[str] = []
    details: dict[str, Any] = {}
    for name, (fn, kwargs, validate) in routines.items():
        ctx.check_stop()
        if not _routine_refuses_first(fn):
            problems.append(f"the {name} does not check for the joint loop first; not called on the live hand")
            metrics.append(Metric(f"{name} refused with the loop running", "not tried", ok=False))
            continue
        refused = None
        try:
            fn(hand, **kwargs)
        except RuntimeError as e:
            refused = str(e)
        except Exception as e:
            problems.append(f"the {name} raised {type(e).__name__} instead of refusing: {e}")
        ok = bool(refused) and "loop" in refused
        if refused is None and not any(name in p for p in problems):
            problems.append(f"the {name} did not refuse while the joint loop runs")
        elif refused is not None and not ok:
            problems.append(f"the {name} refused without naming the joint loop: {refused}")
        metrics.append(Metric(f"{name} refused with the loop running", "yes" if refused else "no", ok=ok))
        details[f"{name} refusal"] = refused

        loopless = types.SimpleNamespace(_loop=None)
        try:
            type(hand)._refuse_routine_while_loop_runs(loopless, fn.__name__)
            allowed = True
        except RuntimeError as e:
            allowed = False
            problems.append(f"the {name} refuses even without a loop: {e}")
        try:
            validate(ctx.service, {})
            console_ok = True
        except _service_error() as e:
            console_ok = False
            problems.append(f"the console would not start the {name}: {e}")
        metrics.append(Metric(f"{name} allowed without a loop", "yes" if allowed and console_ok else "no",
                              ok=allowed and console_ok))
    note = (" The console cannot stop its own session's loop, so \"once it is stopped\" is checked on the same "
            "hand class with no loop and with the console's own start checks; its operations run on a "
            "loop-free maintenance connection.")
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + note, metrics=metrics, details=details)
    return CheckResult(status="pass", summary="both routines refuse while the joint loop runs and are allowed "
                       "without it." + note, metrics=metrics, details=details)


# ----- tension sweep ---------------------------------------------------------------


@register("tension_sweep_runs")
def tension_sweep_runs(ctx: CheckContext) -> CheckResult:
    """A3: the console's tension sweep runs on every finger joint with the
    family defaults, saves a dataset and carries on past a stall."""
    from orca_ui.hand import sweeps
    from orca_core.maintenance.setup_file import setup_path

    blocked = _no_hand(ctx) or _busy(ctx)
    if blocked:
        return blocked
    service = ctx.service
    supervisor = service.supervisor
    config = supervisor.config
    expected = _finger_joints(config, _absent_joints(service))
    before = {name for name, _ in sweeps.for_hand(config, supervisor.hand_id)}
    ctx.progress(0.05, "tension sweep running")
    try:
        snapshot = _run_operation(ctx, "tension_sweep", {"note": f"hardware test {ctx.step.id}"})
    except _service_error() as e:
        return CheckResult(status="error", summary=f"the console refused to start the sweep: {e}")
    ctx.progress(0.9, "reading the saved dataset")
    _wait_connected(ctx)
    if snapshot.get("state") != "done" or snapshot.get("detail") == "stopped":
        return CheckResult(status="fail", summary=f"the sweep did not complete: {snapshot.get('error') or snapshot.get('detail')}",
                           details={"operation": snapshot})
    saved = (snapshot.get("result") or {}).get("saved")
    dataset = sweeps.dataset(config, saved) if saved else None
    problems: list[str] = []
    if not saved or saved in before:
        problems.append("no new sweep dataset was saved")
    if dataset is None:
        problems.append(f"the tension_sweeps section of {setup_path(config)} has no entry {saved!r}")
    results = (dataset or {}).get("results") or []
    repeats = int((dataset or {}).get("repeats") or 1)
    swept = sorted({r.get("joint") for r in results})
    missing = [j for j in expected if j not in swept]
    if missing:
        problems.append(f"not swept: {', '.join(missing)}")
    complete = len(results) >= len(expected) * 2 * repeats
    if not complete:
        problems.append(f"{len(results)} sweeps recorded, {len(expected) * 2 * repeats} expected")
    stalled = [f"{r.get('joint')} {r.get('sense')}" + (f" ({r.get('skipped')})" if r.get("skipped") else
               f" ({float(r.get('short_deg') or 0):.0f}° short)")
               for r in results if r.get("skipped") or float(r.get("short_deg") or 0) > 2]
    metrics = [
        Metric("dataset", saved, ok=bool(saved) and saved not in before),
        Metric("joints swept", len(swept), unit=f"of {len(expected)}", ok=not missing),
        Metric("sweeps recorded", len(results), unit=f"of {len(expected) * 2 * repeats}", ok=complete),
        Metric("stalled or skipped", len(stalled)),
    ]
    rows = _sweep_rows(results)
    series = [Series(name="mean current per sweep", x=[float(i) for i in range(len(rows))],
                     y=[float(r["mean_ma"] or 0.0) for r in rows], x_label="sweep #", y_label="mA")] if rows else []
    details = {"dataset": saved, "stalled": stalled, "results": rows, "operation": snapshot.get("result")}
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + ".", metrics=metrics, series=series,
                           details=details)
    summary = f"swept {len(swept)} joints, saved as {saved}"
    summary += f"; recorded stalls and carried on: {', '.join(stalled)}." if stalled else "; no joint stalled."
    return CheckResult(status="pass", summary=summary, metrics=metrics, series=series, details=details)


# ----- guided tensioning -----------------------------------------------------------


@register("guided_tension_finished")
def guided_tension_finished(ctx: CheckContext) -> CheckResult:
    """A4a: the guided tensioning the person ran completed and was recorded;
    the pull's configured limit is the hand's max_current."""
    from orca_ui.hand.operations import hand_ops

    service = ctx.service
    since = _step_started(ctx)
    runs = [op for op in _step_operations(ctx, ctx.step.id) if op.get("kind") == "guided_tension"]
    if not runs:
        manager = service.operation_manager
        last = manager.snapshot() if manager is not None else None
        if last and last.get("kind") == "guided_tension" and last.get("state") in ("done", "error") \
                and (since is None or float(last.get("started_at") or 0) >= since.timestamp() - 2):
            runs = [last]
    if not runs:
        return CheckResult(status="fail", summary="no guided tensioning finished while this step was open")
    run = runs[-1]
    result = run.get("result") or {}
    completed = run.get("state") == "done" and bool(result.get("completed"))
    record = hand_ops.last_tension(service.supervisor.config) or {}
    recorded = _is_new(record.get("completed_at"), since)

    session = service.session
    config = session.hand.config if session is not None else service.supervisor.config
    try:
        tension_ma = config.tension_current
        max_ma = config.max_current
    except Exception:
        tension_ma = max_ma = None
    pull_ok = None if isinstance(max_ma, str) or max_ma is None else int(tension_ma) == int(max_ma)
    metrics = [
        Metric("completed", "yes" if completed else "no", ok=completed),
        Metric("rounds", result.get("rounds")),
        Metric("recorded as last tension", "yes" if recorded else "no", ok=recorded),
        Metric("configured pull limit", tension_ma, unit="mA", ok=pull_ok),
        Metric("max_current", max_ma, unit="mA"),
    ]
    problems = []
    if not completed:
        problems.append(f"guided tensioning ended {run.get('state')} without completing"
                        + (f": {run.get('error')}" if run.get("error") else ""))
    if not recorded:
        problems.append("setup.yaml's last_tension was not written during this step")
    if pull_ok is False:
        problems.append(f"the pull is configured at {tension_ma} mA, max_current is {max_ma} mA")
    from orca_ui.hardware_tests.checks.evidence import read_back

    limits = read_back(ctx, ctx.step.id, runs)
    if limits is None:
        note = (" The pull current is read from the hand's config (what orca_core uses when nothing overrides it); "
                "this step has no read-back of the limits the motors held.")
    else:
        metrics += limits["metrics"]
        problems += limits["problems"]
        note = " Every limit written was read back from the motors and judged against the hold and tension currents."
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + note, metrics=metrics,
                           details={"operation": run, "last_tension": record})
    return CheckResult(status="pass", summary=f"completed in {result.get('rounds')} round(s) and recorded." + note,
                       metrics=metrics, details={"operation": run, "last_tension": record})


# ----- hardware version ------------------------------------------------------------


@register("hardware_version_reported")
def hardware_version_reported(ctx: CheckContext) -> CheckResult:
    """A8a: the console resolved a hardware version and knows where it came from."""
    status = ctx.service.status()
    version = status.get("hardware_version")
    source = hardware_version_source(ctx.service, status)
    metrics = [
        Metric("hardware version", version, ok=version is not None),
        Metric("source", source or "unknown", ok=source is not None),
        Metric("board reports", status.get("board_hardware_version")),
        Metric("pinned in config", "yes" if status.get("hardware_version_pinned") else "no"),
    ]
    if version is None:
        return CheckResult(status="fail", summary="the console has no hardware version for this hand", metrics=metrics)
    if source is None:
        return CheckResult(status="fail", summary=f"version {version} is in force but neither the board "
                           f"({status.get('board_hardware_version')}) nor a pin accounts for it", metrics=metrics)
    return CheckResult(status="pass", summary=f"version {version}, from the {source}", metrics=metrics)


# ----- motor reboot ----------------------------------------------------------------


@register("motor_reboot_torque_on")
def motor_reboot_torque_on(ctx: CheckContext) -> CheckResult:
    """A10: with the hand holding a pose, reboot one motor; it answers again
    and the others keep their position."""
    blocked = _no_hand(ctx) or _busy(ctx)
    if blocked:
        return blocked
    service = ctx.service
    session = service.session
    if not service.hand_info().get("reboot_supported"):
        return CheckResult(status="skipped", summary="this motor family has no reboot instruction")
    config = session.hand.config
    joint = str(ctx.step.params.get("joint") or "")
    motor = config.joint_to_motor_map.get(joint)
    if motor is None:
        return CheckResult(status="error", summary=f"this hand has no motor for {joint!r}")
    motor = int(motor)
    tolerance = float(ctx.step.params.get("hold_tolerance_rad", 0.05))
    settle_s = float(ctx.step.params.get("settle_s", 1.0))
    was_torqued = bool(service.status().get("torque_enabled"))
    ServiceError = _service_error()
    try:
        if not was_torqued:
            ctx.log("enabling torque to hold the current pose")
            service.enable_torque()
        _wait(ctx, settle_s)
        before = service.motor_snapshot()
        ctx.log(f"rebooting motor {motor} ({joint})")
        reboot = service.reboot_motor(motor)
        _wait(ctx, settle_s)
        after = service.motor_snapshot()
        torque_after = bool(service.status().get("torque_enabled"))
    except ServiceError as e:
        return CheckResult(status="fail", summary=f"the console refused: {e}")
    finally:
        if not was_torqued:
            try:
                service.disable_torque()
            except Exception as e:
                ctx.log(f"could not disable torque again: {e}")

    by_id_before = {m["id"]: m for m in before["motors"]}
    by_id_after = {m["id"]: m for m in after["motors"]}
    rebooted = by_id_after.get(motor) or {}
    answers = bool(reboot.get("read_back")) and rebooted.get("position") is not None
    drift = {
        mid: abs(float(by_id_after[mid]["position"]) - float(m["position"]))
        for mid, m in by_id_before.items()
        if mid != motor and mid in by_id_after and m.get("position") is not None
        and by_id_after[mid].get("position") is not None
    }
    worst = max(drift, key=drift.get) if drift else None
    held = worst is None or drift[worst] <= tolerance
    new_errors = [mid for mid, m in by_id_after.items()
                  if mid != motor and m.get("hw_error_flags") and not by_id_before.get(mid, {}).get("hw_error_flags")]
    metrics = [
        Metric("reboot allowed", "yes", ok=True),
        Metric(f"motor {motor} answers again", "yes" if answers else "no", ok=answers),
        Metric("latched error cleared", reboot.get("cleared")),
        Metric("largest drift of the other motors", None if worst is None else round(drift[worst], 4),
               unit="rad", ok=held),
        Metric("console torque on afterwards", "yes" if torque_after else "no", ok=torque_after),
        Metric("other motors newly latched", len(new_errors), ok=not new_errors),
    ]
    series = [Series(name="drift per motor", x=[float(mid) for mid in drift], y=[float(v) for v in drift.values()],
                     x_label="motor id", y_label="rad")] if drift else []
    problems = []
    if not answers:
        problems.append(f"motor {motor} did not answer after the reboot")
    if not held:
        problems.append(f"motor {worst} moved {drift[worst]:.3f} rad (limit {tolerance:g})")
    if not torque_after:
        problems.append("the console reports torque off after the reboot")
    if new_errors:
        problems.append(f"motors {new_errors} latched an error")
    note = (" Per-motor torque cannot be read back through the console; holding is judged from the other "
            "motors' positions.")
    details = {"reboot": reboot, "before": before["motors"], "after": after["motors"]}
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + note, metrics=metrics, series=series,
                           details=details)
    return CheckResult(status="pass", summary=f"motor {motor} ({joint}) rebooted and answered; the others held "
                       f"within {tolerance:g} rad." + note, metrics=metrics, series=series, details=details)


# ----- current defaults ------------------------------------------------------------


_CURRENT_FIELDS = (
    ("max_current", "default_max_current_ma"),
    ("calibration_current", "default_calibration_current_ma"),
    ("wrist_calibration_current", "default_calibration_current_ma"),
)


@register("current_defaults")
def current_defaults(ctx: CheckContext) -> CheckResult:
    """A11: currents the config leaves on ``default`` resolved to the connected
    motor family's own values."""
    service = ctx.service
    session = service.session
    if session is None or not session.caps.motors:
        return CheckResult(status="error", summary="the hand is not connected: currents resolve when it connects")
    config_path = service.supervisor.config.config_path
    raw = type(service.supervisor.config).from_config_path(config_path=config_path)
    resolved = session.hand.config
    client_cls = type(session.hand.motor_client)
    family = getattr(resolved, "motor_type", None) or client_cls.__name__
    metrics: list[Metric] = []
    problems: list[str] = []
    checked = 0
    for field, attr in _CURRENT_FIELDS:
        configured = getattr(raw, field, None)
        live = getattr(resolved, field, None)
        family_ma = getattr(client_cls, attr, None)
        if isinstance(configured, str) and configured.strip().lower() == "default":
            checked += 1
            ok = live is not None and family_ma is not None and int(live) == int(family_ma)
            if not ok:
                problems.append(f"{field} is on default but resolved to {live}, the {family} default is {family_ma}")
            metrics.append(Metric(field, live, unit="mA", main=None, ok=ok))
            metrics.append(Metric(f"{field} family default", family_ma, unit="mA"))
        elif configured is None:
            metrics.append(Metric(field, "follows calibration_current" if live is None else live, unit="mA"))
        else:
            metrics.append(Metric(f"{field} (pinned in config)", configured, unit="mA"))
    metrics.append(Metric("console current ceiling", service.max_current, unit="mA"))
    if checked == 0:
        return CheckResult(status="skipped", summary="this hand's config pins every current; none is left on default",
                           metrics=metrics)
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + ".", metrics=metrics)
    return CheckResult(status="pass", summary=f"{checked} current(s) left on default resolved to the {family} "
                       "defaults.", metrics=metrics)


# ----- observations ----------------------------------------------------------------


@register("sweep_stall_variants")
def sweep_stall_variants(ctx: CheckContext) -> CheckResult:
    """C2: the thumb sweep with the family's hold current, then with the motors
    not being swept holding lower. Recorded only."""
    from orca_ui.hand import sweeps
    from orca_ui.hand.operations.tension_sweep import SETTING_BOUNDS, sweep_defaults

    blocked = _no_hand(ctx) or _busy(ctx)
    if blocked:
        return blocked
    service = ctx.service
    config = service.supervisor.config
    thumb = [j for j in _finger_joints(config, _absent_joints(service)) if j.startswith("thumb_")]
    if not thumb:
        return CheckResult(status="skipped", summary="this hand has no thumb joint with a motor to sweep")
    defaults = sweep_defaults(service)
    hold = defaults.get("hold_current_ma")
    if hold is None:
        return CheckResult(status="error", summary="the motor family is unknown, so the sweep has no hold current")
    low_bound = SETTING_BOUNDS["hold_current_ma"][0]
    lower = max(low_bound, round(float(hold) * float(ctx.step.params.get("hold_fraction", 0.5))))
    variants = [("family hold", float(hold)), ("lower hold", float(lower))]
    metrics: list[Metric] = []
    details: dict[str, Any] = {"joints": thumb, "variants": {}}
    for index, (name, hold_ma) in enumerate(variants):
        ctx.progress(index / (len(variants) + 1), f"thumb sweep, {name} {hold_ma:g} mA")
        try:
            snapshot = _run_operation(ctx, "tension_sweep", {
                "joints": thumb, "settings": {"hold_current_ma": hold_ma},
                "note": f"hardware test {ctx.step.id}: {name} {hold_ma:g} mA"})
        except _service_error() as e:
            return CheckResult(status="error", summary=f"the console refused to start the sweep: {e}",
                               metrics=metrics, details=details)
        _wait_connected(ctx)
        saved = (snapshot.get("result") or {}).get("saved")
        results = (sweeps.dataset(config, saved) or {}).get("results") or [] if saved else []
        details["variants"][name] = {"hold_ma": hold_ma, "dataset": saved, "state": snapshot.get("state"),
                                     "error": snapshot.get("error"), "results": _sweep_rows(results)}
        for r in results:
            metrics.append(Metric(f"{r.get('joint')} {r.get('sense')} short ({name})",
                                  round(float(r.get("short_deg") or 0.0), 1), unit="°"))
    details["variants"]["others off"] = {"skipped": "the sweep holds every motor it is not sweeping at one "
                                         f"current of at least {low_bound:g} mA; it cannot leave them off"}
    summary = (f"thumb swept with the others holding at {variants[0][1]:g} mA and at {variants[1][1]:g} mA. "
               "The sweep sets one hold current for every motor it is not sweeping, so 'the other thumb motors "
               "lower' ran as 'every other motor lower'; the 'others off' variant is not available.")
    return CheckResult(status="observed", summary=summary, metrics=metrics, details=details)


@register("ring_motor_during_thumb")
def ring_motor_during_thumb(ctx: CheckContext) -> CheckResult:
    """C3: did the ring finger move while the slack test tested the thumb?
    Reads the readings recorded while the slack-test step was open."""
    from orca_ui.hardware_tests import store
    from orca_ui.streaming import topics as T

    source = str(ctx.step.params.get("source_step", "A1"))
    folder = ctx.step_dir(source) if hasattr(ctx, "step_dir") else None
    if folder is None:
        found = ctx.step_result(source) or {}
        folder = found.get("dir")
    if not folder:
        return CheckResult(status="skipped", summary=f"step {source} is not part of this session")
    from pathlib import Path

    readings = store.read_jsonl(Path(folder) / "readings.jsonl")
    if not readings:
        return CheckResult(status="skipped", summary=f"no readings were recorded while step {source} was open")
    testing_thumb = False
    windows = 0
    ring: dict[str, list[tuple[float, float]]] = {}
    for line in readings:
        topics = line.get("topics") or {}
        op = (topics.get(T.OPERATION_STATE) or {}).get("data")
        if op:
            extra = op.get("extra") or {}
            now_thumb = (op.get("kind") == "slack_test" and extra.get("step") == "testing"
                         and str(extra.get("joint") or "").startswith("thumb_"))
            windows += int(now_thumb and not testing_thumb)
            testing_thumb = now_thumb
        if not testing_thumb:
            continue
        for topic in (T.JOINTS_MEASURED, T.JOINTS_ESTIMATE):
            angles = ((topics.get(topic) or {}).get("data") or {}).get("angles") or {}
            for joint, value in angles.items():
                if joint.startswith("ring_") and value is not None:
                    ring.setdefault(f"{joint} ({topic.split('.')[-1]})", []).append((float(line["t"]), float(value)))
    if windows == 0:
        return CheckResult(status="skipped", summary=f"the readings of step {source} hold no slack test on a thumb joint")
    if not any(len(v) >= 2 for v in ring.values()):
        return CheckResult(status="skipped", summary=(
            f"the thumb was tested in {windows} stretch(es), but no ring-finger reading was recorded then: "
            "the slack test holds the hand in maintenance, and the console streams no motor or joint positions "
            "then. Answering this needs the routine itself to record every motor's position while it tests a "
            "joint."))
    t0 = min(t for samples in ring.values() for t, _ in samples)
    metrics = [Metric(f"{name} range", round(max(v for _, v in samples) - min(v for _, v in samples), 2), unit="°")
               for name, samples in ring.items()]
    series = [Series(name=name, x=[t - t0 for t, _ in samples], y=[v for _, v in samples], y_label="°")
              for name, samples in ring.items()]
    moved = max(m.value for m in metrics)
    return CheckResult(status="observed", summary=f"ring joints moved up to {moved:.1f}° while the thumb was tested "
                       f"({windows} stretch(es)).",
                       metrics=metrics, series=series)

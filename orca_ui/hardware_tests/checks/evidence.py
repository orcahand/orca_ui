"""Checks that judge a hands-on step from what the session recorded: the
operation log, finished operations, live readings and files the person saved in
the step's folder, plus read-only looks at the console. None of them moves the
hand.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional

from orca_ui.hardware_tests import store
from orca_ui.hardware_tests.checks.base import CheckContext, register
from orca_ui.hardware_tests.checks.console import (
    _absent_joints,
    _family,
    _finger_joints,
    _step_events,
    _step_operations,
)
from orca_ui.hardware_tests.model import CheckResult, Metric

LIMITS_PREFIX = "current limits ("
LIMITS_SPLIT = "), asked→held mA:"
_LIMIT_CELL = re.compile(r"(\w+) ([\d.]+)→([\d.]+|none)")
_HOLD_SET = re.compile(r"^(hold (ap|mcp|pip)) set to ([\d.]+) mA$")
AGAIN_SUFFIX = ": tested again, its earlier pass dropped"
_LATCHED = re.compile(r"^motor (\d+) \((\w+)\) has latched (.+?) and is not holding")
_CLEARED = re.compile(r"^motor (\d+) cleared and holding again")
_AUTO_REBOOT = re.compile(r"^Motor (\d+) overload detected")
SCRIPT_LOGS = ("calibrate.log", "guided_tension.log")
SCRIPT_FAILURES = ("Traceback (most recent call last)", "interrupted", "cannot run", "Failed to connect")


# ----- shared helpers ----------------------------------------------------------------


def _operation_lines(events: Iterable[dict]) -> list[str]:
    return [e.get("line") or "" for e in events if e.get("type") == "operation_log"]


def _live_config(service):
    session = getattr(service, "session", None)
    return session.hand.config if session is not None else service.supervisor.config


def parse_limit_line(line: str) -> Optional[dict]:
    """A read-back line from guided tensioning, as phase, stage and per-joint
    (asked, held) mA; ``held`` is None for a motor without a current register."""
    if not line.startswith(LIMITS_PREFIX) or LIMITS_SPLIT not in line:
        return None
    head, _, rest = line.partition(LIMITS_SPLIT)
    phase, _, stage = head[len(LIMITS_PREFIX):].partition(", ")
    limits = {joint: (float(asked), None if held == "none" else float(held))
              for joint, asked, held in _LIMIT_CELL.findall(rest)}
    return {"phase": phase, "stage": stage or None, "limits": limits, "mismatch": "MISMATCH on" in rest}


def _allowed_holds(ctx: CheckContext, lines: list[str], runs: list[dict]) -> Callable[[str], set]:
    """The hold currents a moved joint may legitimately run at during the step:
    its own config entry, else its group's default, any value the person set,
    and the values each run started or ended with."""
    from orca_ui.hand.operations.guided_tension import default_currents, fixed_holds, joint_group

    config = ctx.service.supervisor.config
    family = _family(ctx.service)
    fixed = fixed_holds(config, family)
    groups: dict[str, set] = {g: set() for g in ("ap", "mcp", "pip")}
    for key, value in default_currents(config, family).items():
        if key.startswith("hold_"):
            groups[key[5:]].add(float(value))
    for line in lines:
        found = _HOLD_SET.match(line)
        if found:
            groups[found.group(2)].add(float(found.group(3)))
    for run in runs:
        for source in (run.get("extra") or {}, (run.get("params") or {}).get("defaults") or {}):
            for group in groups:
                if isinstance(source.get(f"hold_{group}"), (int, float)):
                    groups[group].add(float(source[f"hold_{group}"]))

    def allowed(joint: str) -> set:
        return {float(fixed[joint])} if joint in fixed else groups[joint_group(joint)]
    return allowed


def judge_limits(entries: list[dict], *, tension_ma: float, stages: dict[str, list[str]],
                 allowed: Callable[[str], set], tolerance: float) -> list[str]:
    """Problems with the read-back lines: a limit that did not land, a frozen
    finger off the tension current, a moved joint off its hold, a pull off the
    tension current. The wrist is left out: it has no current register on every hand."""
    problems: list[str] = []
    for entry in entries:
        where = entry["phase"] + (f", {entry['stage']}" if entry["stage"] else "")
        moved = set(stages.get(entry["stage"] or "", ()))
        for joint, (asked, held) in entry["limits"].items():
            if joint == "wrist":
                continue
            if held is None:
                problems.append(f"{where}: {joint} did not read back")
            elif abs(held - asked) > tolerance:
                problems.append(f"{where}: {joint} asked {asked:g} mA, holds {held:g} mA")
            if entry["phase"] == "range check":
                if joint in moved:
                    options = allowed(joint)
                    if not any(abs(asked - a) <= tolerance for a in options):
                        problems.append(f"{where}: moved {joint} at {asked:g} mA, expected "
                                        f"{' or '.join(f'{a:g}' for a in sorted(options))} mA")
                elif abs(asked - tension_ma) > tolerance:
                    problems.append(f"{where}: frozen {joint} at {asked:g} mA, expected the tension "
                                    f"current {tension_ma:g} mA")
            elif entry["phase"] == "pull" and abs(asked - tension_ma) > tolerance:
                problems.append(f"{where}: {joint} pulled at {asked:g} mA, expected {tension_ma:g} mA")
    return problems


def read_back(ctx: CheckContext, step_id: str, runs: list[dict]) -> Optional[dict]:
    """Metrics and problems from the step's current read-back lines; None when
    the step has none (an orca_core without the read-back)."""
    from orca_ui.hand.operations import hand_ops
    from orca_ui.hand.operations.guided_tension import LIMIT_TOLERANCE_MA

    lines = _operation_lines(_step_events(ctx, step_id))
    entries = [e for e in (parse_limit_line(line) for line in lines) if e is not None]
    if not entries:
        return None
    tension_ma = float(_live_config(ctx.service).tension_current)
    stages = {s["key"]: list(s["joints"]) for s in hand_ops.range_stages()}
    problems = judge_limits(entries, tension_ma=tension_ma, stages=stages,
                            allowed=_allowed_holds(ctx, lines, runs), tolerance=LIMIT_TOLERANCE_MA)
    checked = [e for e in entries if e["phase"] == "range check"]
    metrics = [
        Metric("limit read-backs", len(entries), unit="lines"),
        Metric("range checks read back", len(checked), unit="stages"),
        Metric("limits off what was asked or expected", len(problems), ok=not problems),
        Metric("tension current (frozen fingers, pull)", tension_ma, unit="mA"),
    ]
    return {"entries": entries, "problems": problems, "metrics": metrics,
            "pulled": any(e["phase"] == "pull" for e in entries)}


def _stage_visits(step_dir: Optional[Path], run_id: str) -> list[tuple[int, int]]:
    """(round, stage index) in the order a run showed its stages, poses and
    range checks alike, from the step's readings."""
    if step_dir is None:
        return []
    visits: list[tuple[int, int]] = []
    for row in store.read_jsonl(step_dir / "readings.jsonl"):
        op = ((row.get("topics") or {}).get("operation.state") or {}).get("data") or {}
        extra = op.get("extra") or {}
        if op.get("run_id") != run_id or extra.get("step") not in ("pose", "range"):
            continue
        visit = (extra.get("round"), extra.get("stage_index"))
        if isinstance(visit[1], int) and (not visits or visits[-1] != visit):
            visits.append(visit)
    return visits


def left_order(visits: list[tuple[int, int]]) -> bool:
    """Whether a round went back or skipped ahead (Back or a sidebar jump)."""
    return any(r1 == r2 and s2 != s1 + 1 for (r1, s1), (r2, s2) in zip(visits, visits[1:]))


# ----- guided tensioning: in-run controls (A4c) ----------------------------------------


@register("guided_tension_controls")
def guided_tension_controls(ctx: CheckContext) -> CheckResult:
    """A4c: one guided tensioning run used Back or a jump, "test again" and a
    mid-run current change, ended cleanly, and every limit it wrote landed."""
    step = ctx.step.id
    runs = [op for op in _step_operations(ctx, step) if op.get("kind") == "guided_tension"]
    if not runs:
        return CheckResult(status="fail", summary="no guided tensioning ran while this step was open")
    run = runs[-1]
    lines = _operation_lines(_step_events(ctx, step))
    again = sorted({line[: -len(AGAIN_SUFFIX)] for line in lines if line.endswith(AGAIN_SUFFIX)})
    changed = [m.group(1) for m in (_HOLD_SET.match(line) for line in lines) if m]
    visits = _stage_visits(ctx.step_dir(step) if hasattr(ctx, "step_dir") else None, run.get("run_id"))
    out_of_order = left_order(visits)
    clean = run.get("state") == "done" and not run.get("error")
    scoring = (run.get("extra") or {}).get("scoring")
    limits = read_back(ctx, step, runs)

    problems: list[str] = []
    if not clean:
        problems.append(f"the run ended {run.get('state')}" + (f": {run.get('error')}" if run.get("error") else ""))
    if not out_of_order:
        problems.append("no Back or jump between fingers was recorded (stages ran in order)")
    if not again:
        problems.append('no "test again" was recorded')
    if not changed:
        problems.append("no hold current was changed during the run")
    if limits is not None:
        problems += limits["problems"]
    metrics = [
        Metric("ended cleanly", "yes" if clean else "no", ok=clean),
        Metric("scoring", scoring),
        Metric("stage order", " → ".join(f"{s + 1}" for _, s in visits) or "—", ok=out_of_order),
        Metric("tested again", ", ".join(again) or "—", ok=bool(again)),
        Metric("currents changed", ", ".join(changed) or "—", ok=bool(changed)),
    ] + (limits["metrics"] if limits else [])
    notes = []
    if limits is None:
        notes.append("Not verified: the limits the motors held (no read-back lines in this step).")
    elif limits["pulled"]:
        notes.append("The Tension step ran, so the tendons moved: calibrate before any step that moves the hand.")
    tail = (" " + " ".join(notes)) if notes else ""
    details = {"operation": run, "limits": limits["entries"] if limits else None}
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + tail, metrics=metrics, details=details)
    return CheckResult(status="pass", summary=f"Back/jump, test again and a current change all used; every limit "
                       f"landed as expected.{tail}", metrics=metrics, details=details)


# ----- travel baseline (A13) -----------------------------------------------------------


@register("guided_tension_baseline")
def guided_tension_baseline(ctx: CheckContext) -> CheckResult:
    """A13: guided tensioning scores against a travel table for every finger
    joint, and every run this session logged that same table."""
    from orca_ui.hand.operations.guided_tension import active_travel_baseline, motor_family

    service = ctx.service
    config = service.supervisor.config
    family = motor_family(service)
    info, travel = active_travel_baseline(config, family)
    expected = _finger_joints(config, _absent_joints(service))
    if travel is None:
        travel = {j: config.expected_motor_travel_deg(j) for j in expected}
    missing = [j for j in expected if not travel.get(j)]
    reader = getattr(ctx, "session_events", None)
    logged = [line[len("scoring against "):] for line in _operation_lines(reader() if reader else [])
              if line.startswith("scoring against ")]
    other = sorted({label for label in logged if label != info["label"]})
    metrics = [
        Metric("scores against", info["label"]),
        Metric("source", info.get("source")),
        Metric("finger joints with a travel", len(expected) - len(missing), unit=f"of {len(expected)}",
               ok=not missing),
        Metric("guided runs this session", len(logged), unit="runs"),
        Metric("runs on another table", len(other), ok=not other),
    ]
    problems = []
    if missing:
        problems.append(f"no expected travel for {', '.join(missing)}")
    if other:
        problems.append(f"runs this session scored against {', '.join(other)}")
    note = (" A hand's own baseline is promoted from a calibration snapshot only on the retired Setup page, so "
            "the shipping console scores against the reference hand or the shared v2.1 block.")
    details = {"baseline": info, "travel": travel, "logged": logged}
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + "." + note, metrics=metrics, details=details)
    return CheckResult(status="pass", summary=f"scores against {info['label']} for all {len(expected)} finger joints"
                       f"{'' if logged else '; no guided run in this session yet'}.{note}",
                       metrics=metrics, details=details)


# ----- latched motors (A14) ------------------------------------------------------------


@register("latched_motor_recovered")
def latched_motor_recovered(ctx: CheckContext) -> CheckResult:
    """A14: every motor that latched a fault during the session was cleared and
    held again; automatic reboots by orca_core are listed too."""
    reader = getattr(ctx, "session_events", None)
    events = reader() if reader else []
    latched: list[dict] = []
    auto: list[str] = []
    for event in events:
        text = event.get("line") or event.get("message") or ""
        when = (event.get("t") or "")[11:19]
        if (found := _LATCHED.match(text)):
            latched.append({"motor": found.group(1), "joint": found.group(2), "flags": found.group(3),
                            "at": when, "step": event.get("step"), "cleared": None})
        elif (found := _CLEARED.match(text)):
            for entry in latched:
                if entry["motor"] == found.group(1) and entry["cleared"] is None:
                    entry["cleared"] = when
        elif event.get("type") == "log_record" and (found := _AUTO_REBOOT.match(text)):
            auto.append(f"motor {found.group(1)} at {when} ({event.get('step')})")
    stuck = [e for e in latched if e["cleared"] is None]
    metrics = [
        Metric("latched (pop-up shown)", len(latched), unit="times"),
        Metric("cleared by a reboot", len(latched) - len(stuck), unit=f"of {len(latched)}", ok=not stuck),
        Metric("rebooted by orca_core itself", len(auto), unit="times"),
    ]
    details = {"latched": latched, "auto_reboots": auto}
    if not latched:
        return CheckResult(status="skipped", summary="no motor latched a fault during this session"
                           + (f"; orca_core rebooted {', '.join(auto)} by itself" if auto else ""),
                           metrics=metrics, details=details)
    rows = "; ".join(f"motor {e['motor']} ({e['joint']}) {e['flags']} at {e['at']} in {e['step']}, "
                     + (f"cleared {e['cleared']}" if e["cleared"] else "never cleared") for e in latched)
    status = "fail" if stuck else "pass"
    tail = f" orca_core also rebooted {', '.join(auto)} by itself." if auto else ""
    return CheckResult(status=status, summary=rows + "." + tail, metrics=metrics, details=details)


# ----- simple tensioning step jumps (A15) ----------------------------------------------


@register("simple_tension_jumps")
def simple_tension_jumps(ctx: CheckContext) -> CheckResult:
    """A15: simple tensioning was restarted from its sidebar (a run stopped and a
    new one started) and every run ended without an error."""
    runs = [op for op in _step_operations(ctx, ctx.step.id) if op.get("kind") == "tension"]
    if not runs:
        return CheckResult(status="fail", summary="no simple tensioning ran while this step was open")
    errors = [r for r in runs if r.get("state") == "error" or r.get("error")]
    stopped_then_new = any(not (r.get("result") or {}).get("released") for r in runs[:-1])
    last = runs[-1]
    ended = "released" if (last.get("result") or {}).get("released") else "cancelled"
    metrics = [
        Metric("runs", len(runs)),
        Metric("restarted from the sidebar", "yes" if stopped_then_new else "no", ok=stopped_then_new),
        Metric("errors", len(errors), ok=not errors),
        Metric("last run", ended),
    ]
    problems = []
    if errors:
        problems.append(f"{len(errors)} run(s) ended with an error: {errors[0].get('error')}")
    if not stopped_then_new:
        problems.append('no "Release & activate again" restart was recorded')
    details = {"operations": runs}
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + ".", metrics=metrics, details=details)
    return CheckResult(status="pass", summary=f"{len(runs)} runs, restarted from the sidebar, the last {ended}; "
                       "jumping between steps without a restart leaves no record and is judged by the person.",
                       metrics=metrics, details=details)


# ----- board picker (B11) --------------------------------------------------------------


@register("board_identity_listed")
def board_identity_listed(ctx: CheckContext) -> CheckResult:
    """B11: the board menu lists the console's own board with its serial and board id."""
    boards = ctx.service.boards()
    if not boards.get("available"):
        return CheckResult(status="skipped", summary="the console offers no board menu here (mock or no scan)")
    own = [b for b in boards.get("boards") or [] if b.get("held_by_console")]
    if not own:
        return CheckResult(status="fail", summary="the board menu does not list the console's own board",
                           details={"boards": len(boards.get("boards") or [])})
    entry = own[0]
    serial, board_id = bool(entry.get("serial")), bool(entry.get("board_id"))
    metrics = [Metric("serial shown", "yes" if serial else "no", ok=serial),
               Metric("board id shown", "yes" if board_id else "no", ok=board_id),
               Metric("boards listed", len(boards.get("boards") or []))]
    if serial and board_id:
        return CheckResult(status="pass", summary="the console's board is listed with its serial and board id.",
                           metrics=metrics)
    return CheckResult(status="fail", summary="the console's board is listed without "
                       + " and ".join(n for n, ok in (("its serial", serial), ("its board id", board_id)) if not ok)
                       + ".", metrics=metrics)


# ----- scripts on the hand (B12) -------------------------------------------------------


def judge_script_logs(folder: Path, *, finger_joints: list[str], v21: bool, tension_ma: float) -> dict:
    """What the two script logs in ``folder`` show: problems and metrics."""
    problems: list[str] = []
    metrics: list[Metric] = []
    texts: dict[str, str] = {}
    for name in SCRIPT_LOGS:
        path = folder / name
        if not path.is_file():
            problems.append(f"{name} is missing from the step folder")
            continue
        text = path.read_text(errors="replace")
        texts[name] = text
        failed = [marker for marker in SCRIPT_FAILURES if marker in text]
        if failed:
            problems.append(f"{name} shows {', '.join(repr(m) for m in failed)}")
    calibrate = texts.get("calibrate.log")
    if calibrate is not None:
        done = [j for j in finger_joints if f"  {j} calibrated (ratio" in calibrate]
        travel = re.findall(r"^  (\w+) motor travel .*\[(ok|OUT OF MARGIN)\]", calibrate, re.M)
        metrics += [Metric("joints calibrated by calibrate.py", len(done), unit=f"of {len(finger_joints)}",
                           ok=len(done) == len(finger_joints)),
                    Metric("travel checks printed", len(travel), ok=(len(travel) > 0) if v21 else None)]
        if len(done) < len(finger_joints):
            problems.append(f"calibrate.py did not calibrate {', '.join(sorted(set(finger_joints) - set(done)))}")
        if v21 and not travel:
            problems.append("calibrate.py printed no travel check on a v2.1 hand")
    guided = texts.get("guided_tension.log")
    if guided is not None:
        finished = "Tensioning complete" in guided or "Finished below 100%" in guided
        slack = "tolerance " in guided
        frozen = sorted({float(v) for v in re.findall(r"frozen at ([\d.]+) mA", guided)})
        frozen_ok = bool(frozen) and all(abs(v - tension_ma) <= 1 for v in frozen)
        metrics += [Metric("guided_tension.py finished", "yes" if finished else "no", ok=finished),
                    Metric("slack scoring", "yes" if slack else "no", ok=slack),
                    Metric("frozen fingers at", ", ".join(f"{v:g}" for v in frozen) or "—", unit="mA",
                           ok=frozen_ok)]
        if not finished:
            problems.append("guided_tension.py did not reach its score and finish")
        if not slack:
            problems.append("guided_tension.py did not score with slack (--scoring slack)")
        if not frozen_ok:
            problems.append(f"guided_tension.py froze the other fingers at {frozen or 'nothing printed'}, "
                            f"expected {tension_ma:g} mA")
    return {"problems": problems, "metrics": metrics}


@register("scripts_on_hand_logs")
def scripts_on_hand_logs(ctx: CheckContext) -> CheckResult:
    """B12: calibrate.py and guided_tension.py ran on the hand to the end, as their
    logs in the step folder show."""
    folder = ctx.step_dir(ctx.step.id) if hasattr(ctx, "step_dir") else ctx.out_dir
    config = _live_config(ctx.service)
    version = ctx.hand.hardware_version
    judged = judge_script_logs(Path(folder), finger_joints=_finger_joints(config, _absent_joints(ctx.service)),
                               v21=version is not None and int(version) // 10 == 21,
                               tension_ma=float(config.tension_current))
    if judged["problems"]:
        return CheckResult(status="fail", summary="; ".join(judged["problems"]) + ".", metrics=judged["metrics"])
    return CheckResult(status="pass", summary="both scripts ran to the end on the hand without an error.",
                       metrics=judged["metrics"])

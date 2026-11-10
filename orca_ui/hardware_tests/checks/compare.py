"""Checks that run a recorder scenario with main's and the branch's orca_core.

``compare_*`` checks run the same scenario on the same hand with both sides,
main first, and decide from the difference: each fills
``Metric(value=<branch>, main=<main>)`` and ``Series(side=...)`` so the tab
shows the two side by side. Where a step's pass rule asks for main's own
repeatability, main runs more than once and the branch has to land inside the
band main's runs span, widened by a floor for measurement noise.

The other checks here (calibration_redrive, calibration_plain_pass,
hardware_version_pin, guided_tension_refusal, calibration_vs_encoders) test
branch-only features and run the branch side alone.
"""

from __future__ import annotations

import contextlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Iterable, Optional

import yaml

from orca_ui.hardware_tests.checks.base import CheckContext, register
from orca_ui.hardware_tests.model import CheckResult, Metric, Series

SIDES = ("main", "branch")
MAX_POINTS = 2000

POSITION_FLOOR_DEG = 1.0
"""Smallest band around main's neutral positions: motor read noise and backlash."""
LIMIT_FLOOR_DEG = 2.0
"""Smallest band around main's calibrated limits: where a stall settles varies run to run."""
CURRENT_FLOOR_FRACTION = 0.15
CURRENT_FLOOR_MA = 10.0
DRIFT_FLOOR_DEG = 2.0
STALL_FLOOR_DEG = 5.0
"""Smallest band around where main's winds stopped a motor; beyond it the tendon itself behaved differently."""
HOLD_SETTLE_S = 1.0
"""Holding samples this soon after the hold starts are left out of the averages."""
REACH_TOL_DEG = 3.0
SAME_ERROR_TOL_DEG = 1.5

SHARED_FLAGS = ("--mock", "--model-name", "--hardware-version", "--no-engage-feedback")
MOCK_RUN_SCRIPTS = ("calibrate.py", "measure_travel.py", "neutral.py", "zero.py")
"""orca_core scripts that run to the end with ``--mock`` and no terminal; the rest
wait for input or run until interrupted, so only their ``--help`` is run."""
SCRIPT_PIN = 21
"""The older v2.1 encoding, which every orca_core still reads as v2.1."""
SCRIPT_TIMEOUT_S = 120.0
V20 = 200
V21 = 210

DETECT_FIELDS = (
    ("model_name", "model"), ("side", "side"), ("motor_type", "motor family"),
    ("motor_port", "motor port"), ("sensing_port", "sensing port"),
    ("tactile_port", "tactile port"), ("has_tactile", "tactile"), ("has_encoders", "encoders"),
)
DETECT_INFO_FIELDS = (("motor_baudrate", "motor baud rate"), ("busy_ports", "busy ports"),
                      ("missing_capabilities", "missing sensors"))


# ----- helpers ----------------------------------------------------------------------------------


def downsample(x: list, y: list, max_points: int = MAX_POINTS) -> tuple[list, list]:
    """At most ``max_points`` points, keeping each bucket's lowest and highest value
    so peaks survive."""
    pairs = [(a, b) for a, b in zip(x, y) if _finite(a) and _finite(b)]
    if len(pairs) <= max_points:
        return [a for a, _ in pairs], [b for _, b in pairs]
    buckets = max(max_points // 2, 1)
    size = len(pairs) / buckets
    xs, ys = [], []
    for b in range(buckets):
        chunk = range(int(b * size), min(int((b + 1) * size), len(pairs)))
        if not chunk:
            continue
        low = min(chunk, key=lambda i: pairs[i][1])
        high = max(chunk, key=lambda i: pairs[i][1])
        for i in sorted({low, high}):
            xs.append(pairs[i][0])
            ys.append(pairs[i][1])
    return xs, ys


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def series(name: str, x: list, y: list, side: str, *, x_label: str = "s",
           y_label: str = "") -> Series:
    xs, ys = downsample(list(x), list(y))
    return Series(name=name, x=xs, y=ys, side=side, x_label=x_label, y_label=y_label)


def read_readings(out_dir: Path) -> list[dict]:
    path = Path(out_dir) / "readings.jsonl"
    rows = []
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def three_digit(version) -> Optional[int]:
    """A hardware version in the three-digit form (2 -> 200, 21 -> 210, 211 stays)."""
    if version is None:
        return None
    version = int(version)
    return version * 100 if version < 10 else version * 10 if version < 100 else version


def _deg(rad) -> Optional[float]:
    return math.degrees(rad) if _finite(rad) else None


def _round(v, digits: int = 2):
    return round(v, digits) if _finite(v) else v


def _text(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(i) for i in v) or "none"
    return str(v)


def _released(ctx: CheckContext):
    """Hold the hand released across several runs, when the runner offers it."""
    release = getattr(ctx.sides, "hand_released", None)
    return release() if callable(release) else contextlib.nullcontext()


def _rel(ctx: CheckContext, path: Path) -> str:
    try:
        return str(Path(path).relative_to(ctx.out_dir))
    except ValueError:
        return str(path)


def _need_sides(ctx: CheckContext, sides: Iterable[str]) -> Optional[CheckResult]:
    reasons = {}
    for side in sides:
        reason = ctx.sides.available(side)
        if reason:
            reasons[side] = reason
    if not reasons:
        return None
    text = "; ".join(f"{side}'s orca_core is not available: {r}" for side, r in reasons.items())
    return CheckResult("error", f"Not run: {text}", details={"unavailable": reasons})


def _args(ctx: CheckContext, **extra) -> dict:
    return {"detected_hardware_version": ctx.hand.hardware_version, **extra}


def _run(ctx: CheckContext, side: str, scenario: str, args: dict, out: Path) -> dict:
    ctx.check_stop()
    result = ctx.sides.run(side, scenario, args, out)
    ctx.check_stop()
    return result


def _problem(result: dict) -> Optional[str]:
    if result.get("available") is False:
        return f"not available on this side: {result.get('reason')}"
    if not result.get("ok"):
        return result.get("error") or "the recorder failed"
    return None


def _brief(ctx: CheckContext, result: dict) -> dict:
    runner = result.get("runner") or {}
    return {
        "ok": result.get("ok"), "available": result.get("available"),
        "reason": result.get("reason"), "error": result.get("error"),
        "orca_core": result.get("orca_core"), "duration_s": result.get("duration_s"),
        "notes": result.get("notes") or [], "warnings": (result.get("log") or [])[:50],
        "folder": _rel(ctx, runner["out_dir"]) if runner.get("out_dir") else None,
    }


def _failed_runs(ctx: CheckContext, results: dict[str, dict]) -> Optional[CheckResult]:
    """A result for runs that did not finish: skipped when every one of them is
    unavailable on its side, else an error naming each failure."""
    problems = {label: _problem(r) for label, r in results.items() if _problem(r)}
    if not problems:
        return None
    details = {"problems": problems, "runs": {k: _brief(ctx, r) for k, r in results.items()}}
    text = "; ".join(f"{label}: {p}" for label, p in problems.items())
    if all(r.get("available") is False for r in results.values()):
        return CheckResult("skipped", f"Not available: {text}", details=details)
    return CheckResult("error", text, details=details)


def _band(values: list[float], floor: float) -> tuple[float, float]:
    """main's band: the span of its runs, widened by that span or ``floor``, whichever is larger."""
    low, high = min(values), max(values)
    slack = max(high - low, floor)
    return low - slack, high + slack


def _mock_caveat(ctx: CheckContext, status: str, summary: str, missing: str) -> tuple[str, str]:
    """orca_core's mock hand streams no ``missing``: a failure there says nothing about the code."""
    if ctx.hand.mock and status == "fail":
        return "skipped", f"Mock hand: orca_core's mock streams no {missing}, so only the plumbing ran ({summary})"
    return status, summary


def _joint_label(joint_by_motor: dict, motor) -> str:
    joint = joint_by_motor.get(str(motor))
    return f"{joint} (motor {motor})" if joint else f"motor {motor}"


# ----- detection --------------------------------------------------------------------------------


@register("compare_detect")
def compare_detect(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    results = {}
    with _released(ctx):
        for i, side in enumerate(SIDES):
            ctx.progress(i / 2, f"detecting with {side}'s orca_core")
            results[side] = _run(ctx, side, "detect", {}, ctx.out_dir / side)
    failed = _failed_runs(ctx, results)
    if failed:
        return failed
    found = {s: (results[s].get("data") or {}).get("detection") or {} for s in SIDES}
    metrics = []
    for field, label in DETECT_FIELDS:
        b, m = found["branch"].get(field), found["main"].get(field)
        metrics.append(Metric(label, _text(b), main=_text(m), ok=b == m))
    for field, label in DETECT_INFO_FIELDS:
        metrics.append(Metric(label, _text(found["branch"].get(field)),
                              main=_text(found["main"].get(field))))
    differ = [m.name for m in metrics if m.ok is False]
    summary = ("Both found the same hand: " + ", ".join(
        f"{m.name} {m.value}" for m in metrics[:3]) if not differ
               else "Detection differs in " + ", ".join(differ))
    return CheckResult("fail" if differ else "pass", summary, metrics=metrics,
                       details={"detection": found,
                                "runs": {s: _brief(ctx, r) for s, r in results.items()}})


# ----- config loading ---------------------------------------------------------------------------


def _loads(entry: Optional[dict]) -> tuple[bool, str]:
    if not entry:
        return False, "missing"
    errors = [f"{variant}: {v.get('error')}" for variant, v in entry.items() if not v.get("ok")]
    return (not errors), ("loads" if not errors else "; ".join(errors))


@register("compare_config_loading")
def compare_config_loading(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    results = {}
    for i, side in enumerate(SIDES):
        ctx.progress(i / 2, f"loading every model with {side}'s orca_core")
        results[side] = _run(ctx, side, "load_configs", {}, ctx.out_dir / side)
    failed = _failed_runs(ctx, results)
    if failed:
        return failed
    models = {s: (results[s].get("data") or {}).get("models") or {} for s in SIDES}
    metrics, broken = [], []
    for name in sorted(set(models["main"]) | set(models["branch"])):
        main_ok, main_text = _loads(models["main"].get(name))
        branch_ok, branch_text = _loads(models["branch"].get(name))
        ok = branch_ok or not main_ok
        if not ok:
            broken.append(name)
        metrics.append(Metric(name, branch_text, main=main_text, ok=ok))
    summary = (f"All {len(metrics)} packaged models that load on main load on the branch"
               if not broken else "Load on main but not on the branch: " + ", ".join(broken))
    return CheckResult("fail" if broken else "pass", summary, metrics=metrics,
                       details={"models": models,
                                "runs": {s: _brief(ctx, r) for s, r in results.items()}})


# ----- plain calibration ------------------------------------------------------------------------


def _limits(result: dict) -> dict[str, list]:
    calibration = (result.get("data") or {}).get("calibration") or {}
    return {str(m): v for m, v in (calibration.get("motor_limits_dict") or {}).items()
            if isinstance(v, list) and len(v) == 2 and all(_finite(x) for x in v)}


def _travel(result: dict) -> dict[str, float]:
    calibration = (result.get("data") or {}).get("calibration") or {}
    return {j: v for j, v in (calibration.get("motor_travel_measured_dict") or {}).items()
            if _finite(v)}


def _outcome_problem(results: dict[str, dict]) -> Optional[str]:
    bad = [f"{label} ended {(r.get('data') or {}).get('outcome')}"
           for label, r in results.items() if (r.get("data") or {}).get("outcome") != "done"]
    return "; ".join(bad) or None


def _total_current_series(ctx: CheckContext, result: dict, side: str, name: str) -> Optional[Series]:
    folder = (result.get("runner") or {}).get("out_dir")
    rows = read_readings(Path(folder)) if folder else []
    x, y = [], []
    for row in rows:
        cur = row.get("cur")
        if isinstance(cur, list) and cur:
            x.append(row.get("t"))
            y.append(sum(abs(c) for c in cur if _finite(c)))
    return series(name, x, y, side, y_label="mA") if x else None


def judge_calibration(main_runs: list[dict], branch: dict, joints: Optional[list] = None,
                      floor_deg: float = LIMIT_FLOOR_DEG) -> tuple[list[Metric], list[str]]:
    """Per calibrated motor: the branch's lower and upper limit inside main's band.
    Returns the metrics and the labels of the limits outside it."""
    branch_limits = _limits(branch)
    main_limits = [_limits(r) for r in main_runs]
    joint_by_motor = (branch.get("data") or {}).get("joint_by_motor") or {}
    floor = math.radians(floor_deg)
    metrics, outside = [], []
    for motor in sorted(branch_limits, key=lambda m: int(m) if m.isdigit() else m):
        joint = joint_by_motor.get(motor)
        if joints and joint not in joints:
            continue
        if not all(motor in limits for limits in main_limits):
            continue
        label = _joint_label(joint_by_motor, motor)
        for index, bound in enumerate(("lower", "upper")):
            values = [limits[motor][index] for limits in main_limits]
            low, high = _band(values, floor)
            value = branch_limits[motor][index]
            ok = low <= value <= high
            if not ok:
                outside.append(f"{label} {bound} limit")
            metrics.append(Metric(f"{label} {bound} limit", _round(_deg(value)), "deg",
                                  main=_round(_deg(statistics.fmean(values))), ok=ok))
    branch_travel = _travel(branch)
    main_travel = [_travel(r) for r in main_runs]
    for joint, value in sorted(branch_travel.items()):
        if joints and joint not in joints:
            continue
        values = [t[joint] for t in main_travel if joint in t]
        metrics.append(Metric(f"{joint} travel", _round(value), "deg",
                              main=_round(statistics.fmean(values)) if values else None))
    return metrics, outside


def plain_pass_overrides(ctx: CheckContext) -> tuple[dict, str]:
    """Config overrides that make both sides calibrate in one plain pass, and why.

    Pinning v2.0 does it, except on a v2.1 hand whose config maps v2.1 joints to
    other motor signs: pinned to v2.0 it would calibrate with the wrong map, so
    the re-drive is switched off instead and the hand keeps its own map."""
    version = three_digit(ctx.hand.hardware_version)
    if version is not None and version // 10 == V21 // 10:
        data = {}
        with contextlib.suppress(Exception):
            data = yaml.safe_load(ctx.sides.config_source("branch")[0].read_text()) or {}
        v21_map = data.get("joint_to_motor_map_v21")
        if v21_map and v21_map != data.get("joint_to_motor_map"):
            return ({"calibration_travel_retries": 0},
                    "both sides calibrate with re-drives off (pinning v2.0 would change this "
                    "hand's joint map), so each makes one plain pass")
    return {"hardware_version": V20}, "both sides calibrate pinned to v2.0 (one plain pass each)"


@register("compare_plain_calibration")
def compare_plain_calibration(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    params = ctx.step.params or {}
    main_count = max(int(params.get("main_runs", 2)), 1)
    joints = params.get("joints")
    overrides, how = plain_pass_overrides(ctx)
    args = _args(ctx, joints=joints, config_overrides=overrides)
    plan = [("main", ctx.out_dir / "main" / f"run{n + 1}") for n in range(main_count)]
    plan.append(("branch", ctx.out_dir / "branch"))
    runs: list[tuple[str, dict]] = []
    with _released(ctx):
        for i, (side, out) in enumerate(plan):
            ctx.progress(i / len(plan), f"calibrating with {side}'s orca_core ({i + 1}/{len(plan)})")
            runs.append((side, _run(ctx, side, "calibrate", args, out)))
    labelled = {(f"main run {i + 1}" if side == "main" else "branch"): r
                for i, (side, r) in enumerate(runs)}
    failed = _failed_runs(ctx, labelled)
    if failed:
        return failed
    details = {"runs": {k: _brief(ctx, r) for k, r in labelled.items()},
               "plain_pass": how, "overrides": overrides}
    unfinished = _outcome_problem(labelled)
    if unfinished:
        return CheckResult("error", f"A calibration did not finish: {unfinished}", details=details)
    main_runs = [r for side, r in runs if side == "main"]
    branch = runs[-1][1]
    metrics, outside = judge_calibration(main_runs, branch, joints)
    if not any(m.ok is not None for m in metrics):
        return CheckResult("error", "No calibrated limits to compare", metrics=metrics,
                           details=details)
    out = []
    for label, result in labelled.items():
        side = "branch" if label == "branch" else "main"
        s = _total_current_series(ctx, result, side, "total current during calibration")
        if s:
            out.append(s)
    for label, result in labelled.items():
        side = "branch" if label == "branch" else "main"
        travel = _travel(result)
        names = sorted(travel)
        out.append(series("travel per joint", list(range(len(names))), [travel[n] for n in names],
                          side, x_label="joint (alphabetical)", y_label="deg"))
    details["joint_order"] = sorted(_travel(branch))
    spread = f"main's {len(main_runs)} run(s) ± {LIMIT_FLOOR_DEG:g}° at least"
    summary = (f"Every limit from the branch lies within {spread}" if not outside
               else f"Outside {spread}: " + ", ".join(outside))
    return CheckResult("fail" if outside else "pass", summary, metrics=metrics, series=out,
                       details=details)


# ----- neutral ----------------------------------------------------------------------------------


MAPPING_FIELDS = ("joint_roms", "joint_roms_v211", "neutral_position", "joint_to_motor_map",
                  "joint_to_motor_map_v21", "joint_inversion")
"""config.yaml keys that turn a joint angle into a motor position."""
MAPPING_TOL_DEG = 0.01


def mapping_overrides(ctx: CheckContext) -> tuple[dict, dict]:
    """The console config's joint-to-motor mapping keys, so both sides' copies map the same,
    and where they came from. The console's calibration was made with that config."""
    console = getattr(ctx.sides, "console_config", None)
    path = console() if callable(console) else None
    if path is None or not Path(path).is_file():
        return {}, {"source": None, "fields": [], "reason": "the console has no config file to take them from"}
    data = yaml.safe_load(Path(path).read_text()) or {}
    overrides = {k: data[k] for k in MAPPING_FIELDS if k in data}
    return overrides, {"source": str(path), "fields": sorted(overrides)}


def _same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if _finite(a) and _finite(b):
        return abs(float(a) - float(b)) <= MAPPING_TOL_DEG
    return a == b


def mapping_difference(main: dict, branch: dict) -> list[str]:
    """Mapping fields the two runs used differently; empty when they map joints alike."""
    m = (main.get("data") or {}).get("mapping")
    b = (branch.get("data") or {}).get("mapping")
    if not isinstance(m, dict) or not isinstance(b, dict):
        return ["a side did not report the mapping it used"]
    return [k for k in sorted(set(m) | set(b)) if not _same(m.get(k), b.get(k))]


def _neutral_positions(result: dict) -> list[dict[str, float]]:
    return [{str(m): v for m, v in (c.get("motor_pos") or {}).items() if _finite(v)}
            for c in (result.get("data") or {}).get("cycles") or []]


def tracking_errors(result: dict) -> dict[str, float]:
    """Per motor: mean neutral position minus the target this side commanded (deg)."""
    targets = (result.get("data") or {}).get("targets") or {}
    cycles = _neutral_positions(result)
    out = {}
    for motor, target in targets.items():
        values = [c[motor] for c in cycles if motor in c]
        if values and _finite(target):
            out[motor] = _deg(statistics.fmean(values) - target)
    return out


def judge_neutral(main: dict, branch: dict,
                  floor_deg: float = POSITION_FLOOR_DEG) -> tuple[list[Metric], list[str]]:
    """Per motor: the branch's mean neutral position inside main's band over its cycles."""
    main_cycles, branch_cycles = _neutral_positions(main), _neutral_positions(branch)
    joint_by_motor = (branch.get("data") or {}).get("joint_by_motor") or {}
    floor = math.radians(floor_deg)
    metrics, outside = [], []
    motors = sorted({m for c in branch_cycles for m in c}, key=lambda m: int(m) if m.isdigit() else m)
    for motor in motors:
        main_values = [c[motor] for c in main_cycles if motor in c]
        branch_values = [c[motor] for c in branch_cycles if motor in c]
        if not main_values or not branch_values:
            continue
        low, high = _band(main_values, floor)
        value = statistics.fmean(branch_values)
        ok = low <= value <= high
        label = _joint_label(joint_by_motor, motor)
        if not ok:
            outside.append(label)
        metrics.append(Metric(label, _round(_deg(value)), "deg",
                              main=_round(_deg(statistics.fmean(main_values))), ok=ok))
    return metrics, outside


@register("compare_neutral")
def compare_neutral(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    cycles = max(int((ctx.step.params or {}).get("cycles", 3)), 1)
    overrides, overlay = mapping_overrides(ctx)
    results = {}
    with _released(ctx):
        for i, side in enumerate(SIDES):
            ctx.progress(i / 2, f"neutral with {side}'s orca_core")
            args = _args(ctx, cycles=cycles, config_overrides=overrides) if overrides else _args(ctx, cycles=cycles)
            results[side] = _run(ctx, side, "neutral", args, ctx.out_dir / side)
    failed = _failed_runs(ctx, results)
    if failed:
        return failed
    details = {"runs": {s: _brief(ctx, r) for s, r in results.items()}, "mapping_overlay": overlay}
    differing = mapping_difference(results["main"], results["branch"])
    if differing:
        details["mapping_used"] = {s: (r.get("data") or {}).get("mapping") for s, r in results.items()}
        return CheckResult("error", "Inconclusive: the two sides map joint angles to motor positions "
                           f"differently ({', '.join(differing)}), so their motor positions are not "
                           "comparable", details=details)
    metrics, outside = judge_neutral(results["main"], results["branch"])
    if not metrics:
        return CheckResult("error", "No motor positions to compare", details=details)
    joint_by_motor = (results["branch"].get("data") or {}).get("joint_by_motor") or {}
    errors = {s: tracking_errors(r) for s, r in results.items()}
    for motor in sorted(errors["branch"], key=lambda m: int(m) if m.isdigit() else m):
        metrics.append(Metric(f"{_joint_label(joint_by_motor, motor)} off its own target",
                              _round(errors["branch"][motor]), "deg",
                              main=_round(errors["main"].get(motor))))
    out = []
    for side in SIDES:
        cycles_read = _neutral_positions(results[side])
        motors = sorted({m for c in cycles_read for m in c}, key=lambda m: int(m) if m.isdigit() else m)
        means = [statistics.fmean([c[m] for c in cycles_read if m in c]) for m in motors]
        out.append(series("neutral position per motor", [int(m) for m in motors if m.isdigit()],
                          [_deg(v) for v, m in zip(means, motors) if m.isdigit()], side,
                          x_label="motor id", y_label="deg"))
    band = f"main's repeatability over {cycles} cycle(s), at least ±{POSITION_FLOOR_DEG:g}°"
    source = f"; both mapped with the console's {', '.join(overlay['fields'])}" if overlay.get("fields") else ""
    summary = (f"Every motor reaches the same neutral within {band}{source}" if not outside
               else f"Outside {band}{source}: " + ", ".join(outside))
    return CheckResult("fail" if outside else "pass", summary, metrics=metrics, series=out,
                       details=details)


# ----- tension hold -----------------------------------------------------------------------------


def hold_profile(result: dict, rows: list[dict]) -> dict:
    """Per motor during the hold (after its first ``HOLD_SETTLE_S``): mean current (mA)
    and how far the motor moved (deg), plus the total current over time."""
    data = result.get("data") or {}
    motor_ids = [str(m) for m in ((result.get("hand") or {}).get("motor_ids") or [])]
    start = (data.get("hold_started_t") or 0.0) + HOLD_SETTLE_S
    end = data.get("hold_ended_t")
    window = [r for r in rows if _finite(r.get("t")) and r["t"] >= start
              and (end is None or r["t"] <= end)]
    currents: dict[str, list] = {m: [] for m in motor_ids}
    positions: dict[str, list] = {m: [] for m in motor_ids}
    for row in window:
        for key, store in (("cur", currents), ("pos", positions)):
            values = row.get(key)
            if isinstance(values, list):
                for motor, v in zip(motor_ids, values):
                    if _finite(v):
                        store[motor].append(v)
    profile = {"current": {}, "drift": {}}
    for motor in motor_ids:
        if currents[motor]:
            profile["current"][motor] = statistics.fmean(currents[motor])
        pos = positions[motor]
        if len(pos) >= 2:
            k = min(5, len(pos) // 2) or 1
            profile["drift"][motor] = _deg(statistics.fmean(pos[-k:]) - statistics.fmean(pos[:k]))
    profile["total"] = (
        [r["t"] for r in rows if isinstance(r.get("cur"), list)],
        [sum(abs(c) for c in r["cur"] if _finite(c)) for r in rows if isinstance(r.get("cur"), list)],
    )
    return profile


def wind_stalls(result: dict, rows: list[dict]) -> dict[str, dict[str, float]]:
    """Per wind pass ("wind -", "wind +"), each motor's position (deg) where the pass
    ended: where its tendon stopped winding."""
    events = result.get("events") or []
    starts = [e["t"] for e in events if e.get("event") == "winding_progress" and _finite(e.get("t"))]
    ramp = [e["t"] for e in events if e.get("event") == "phase" and e.get("phase") == "ramp"
            and _finite(e.get("t"))]
    motor_ids = [str(m) for m in ((result.get("hand") or {}).get("motor_ids") or [])]
    ends = starts[1:] + ramp[:1]
    out: dict[str, dict[str, float]] = {}
    for name, start, end in zip(("wind -", "wind +"), starts, ends):
        inside = [r for r in rows if _finite(r.get("t")) and start <= r["t"] < end
                  and isinstance(r.get("pos"), list)]
        if not inside:
            continue
        last = inside[-1]["pos"]
        out[name] = {m: _deg(v) for m, v in zip(motor_ids, last) if _finite(v)}
    return out


def stalled_elsewhere(main_profiles: list[dict], branch: dict, motor: str) -> list[str]:
    """Wind passes in which ``branch`` stalled ``motor`` outside main's stall range."""
    odd = []
    for name, stalls in (branch.get("stalls") or {}).items():
        main_stalls = [p["stalls"][name][motor] for p in main_profiles
                       if motor in (p.get("stalls") or {}).get(name, {})]
        if motor in stalls and main_stalls:
            low, high = _band(main_stalls, STALL_FLOOR_DEG)
            if not low <= stalls[motor] <= high:
                odd.append(name)
    return odd


def _floor_from_spread(per_motor: list[list[float]], floor: float) -> float:
    """``floor``, or the median run-to-run spread of main's motors when that is larger."""
    spreads = [max(v) - min(v) for v in per_motor if len(v) >= 2]
    return max(floor, statistics.median(spreads)) if spreads else floor


def judge_hold(main_profiles: list[dict], branch_runs: list[dict], joint_by_motor: dict
               ) -> tuple[list[Metric], list[str], list[str], list[str]]:
    """``(metrics, outside, mechanical, unjudged)``. A branch run whose wind stalled a motor
    outside main's stall range is a mechanically different run for that motor: reported,
    not judged on its current. A motor no branch run could be judged on is ``unjudged``."""
    metrics, outside, mechanical, unjudged = [], [], [], []
    motors = sorted({m for b in branch_runs for m in b["current"]},
                    key=lambda m: int(m) if m.isdigit() else m)
    current_spread = _floor_from_spread(
        [[p["current"][m] for p in main_profiles if m in p["current"]] for m in motors], 0.0)
    drift_floor = _floor_from_spread(
        [[p["drift"][m] for p in main_profiles if m in p["drift"]] for m in motors], DRIFT_FLOOR_DEG)
    for motor in motors:
        label = _joint_label(joint_by_motor, motor)
        currents = [p["current"][motor] for p in main_profiles if motor in p["current"]]
        drifts = [p["drift"][motor] for p in main_profiles if motor in p["drift"]]
        judged = False
        for n, branch in enumerate(branch_runs, start=1):
            run = f"branch run {n}"
            odd = stalled_elsewhere(main_profiles, branch, motor)
            if odd:
                mechanical.append(f"{label} in {run} ({', '.join(odd)} stalled elsewhere)")
                continue
            judged = True
            if currents and motor in branch["current"]:
                mean = statistics.fmean(currents)
                floor = max(CURRENT_FLOOR_FRACTION * abs(mean), CURRENT_FLOOR_MA, current_spread)
                low, high = _band(currents, floor)
                value = branch["current"][motor]
                ok = low <= value <= high
                if not ok:
                    outside.append(f"{label} current in {run}")
                metrics.append(Metric(f"{label} holding current, {run}", _round(value, 1), "mA",
                                      main=_round(mean, 1), ok=ok))
            if drifts and motor in branch["drift"]:
                low, high = _band(drifts, drift_floor)
                value = branch["drift"][motor]
                ok = low <= value <= high
                if not ok:
                    outside.append(f"{label} motion in {run}")
                metrics.append(Metric(f"{label} motion while holding, {run}", _round(value), "deg",
                                      main=_round(statistics.fmean(drifts)), ok=ok))
        if not judged:
            unjudged.append(label)
    return metrics, outside, mechanical, unjudged


@register("compare_tension_hold")
def compare_tension_hold(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    params = ctx.step.params or {}
    hold_s = float(params.get("hold_s", 10))
    main_count = max(int(params.get("main_runs", 3)), 2)
    branch_count = max(int(params.get("branch_runs", 2)), 1)
    plan = interleaved_plan(main_count, branch_count)
    runs: list[tuple[str, str, dict]] = []
    with _released(ctx):
        for i, (side, label) in enumerate(plan):
            ctx.progress(i / len(plan), f"tensioning with {side}'s orca_core ({i + 1}/{len(plan)})")
            out = ctx.out_dir / side / f"run{label.split()[-1]}"
            runs.append((side, label, _run(ctx, side, "tension_hold", _args(ctx, hold_s=hold_s), out)))
    labelled = {label: r for _, label, r in runs}
    failed = _failed_runs(ctx, labelled)
    if failed:
        return failed
    profiles = []
    for side, label, result in runs:
        rows = read_readings(Path((result.get("runner") or {}).get("out_dir", "")))
        profile = hold_profile(result, rows)
        profile["stalls"] = wind_stalls(result, rows)
        profiles.append((side, label, profile))
    joint_by_motor = (runs[-1][2].get("data") or {}).get("joint_by_motor") or {}
    main_profiles = [p for s, _, p in profiles if s == "main"]
    branch_profiles = [p for s, _, p in profiles if s == "branch"]
    metrics, outside, mechanical, unjudged = judge_hold(main_profiles, branch_profiles, joint_by_motor)
    for motor in sorted({m for _, _, p in profiles for stalls in p["stalls"].values() for m in stalls},
                        key=lambda m: int(m) if m.isdigit() else m):
        for name in ("wind -", "wind +"):
            main_values = [p["stalls"][name][motor] for p in main_profiles
                           if motor in p["stalls"].get(name, {})]
            branch_values = [p["stalls"][name][motor] for p in branch_profiles
                             if motor in p["stalls"].get(name, {})]
            if main_values and branch_values:
                metrics.append(Metric(f"{_joint_label(joint_by_motor, motor)} {name} stall",
                                      _round(statistics.fmean(branch_values)), "deg",
                                      main=_round(statistics.fmean(main_values))))
    details = {"runs": {k: _brief(ctx, r) for k, r in labelled.items()}, "order": [l for _, l in plan],
               "hold_s": hold_s, "settle_s": HOLD_SETTLE_S, "mechanical": mechanical,
               "unjudged": unjudged, "stalls": {l: p["stalls"] for _, l, p in profiles}}
    if not metrics:
        return CheckResult("error", "No holding samples to compare", details=details)
    out = []
    for side, label, profile in profiles:
        out.append(series(f"total current, {label}", *profile["total"], side, y_label="mA"))
        motors = sorted(profile["current"], key=lambda m: int(m) if m.isdigit() else m)
        out.append(series("holding current per motor", [int(m) for m in motors],
                          [profile["current"][m] for m in motors], side,
                          x_label="motor id", y_label="mA"))
    band = (f"main's {main_count} runs, alternated with {branch_count} branch run(s) (at least "
            f"±{CURRENT_FLOOR_FRACTION:.0%} or ±{CURRENT_FLOOR_MA:g} mA current, ±{DRIFT_FLOOR_DEG:g}° motion, "
            "or main's typical run-to-run spread)")
    notes = (f" Mechanically different, not judged on current: {', '.join(mechanical)}." if mechanical else "")
    if outside:
        return CheckResult("fail", f"Outside {band}: " + ", ".join(outside) + "." + notes,
                           metrics=metrics, series=out, details=details)
    if unjudged:
        return CheckResult("observed", f"No regression within {band}, but no branch run could be "
                           f"judged for {', '.join(unjudged)}: its tendon behaved differently in every "
                           "branch run." + notes, metrics=metrics, series=out, details=details)
    return CheckResult("pass", f"Every tendon holds with the same current and motion, within {band}."
                       + notes, metrics=metrics, series=out, details=details)


def interleaved_plan(main_count: int, branch_count: int) -> list[tuple[str, str]]:
    """Alternate the sides, starting and ending on main when it has the extra run, so neither
    side always starts where the other left the tendons."""
    plan, m, b = [], 0, 0
    while m < main_count or b < branch_count:
        if m < main_count and (m <= b or b >= branch_count):
            m += 1
            plan.append(("main", f"main run {m}"))
        else:
            b += 1
            plan.append(("branch", f"branch run {b}"))
    return plan


# ----- joint loop -------------------------------------------------------------------------------


def loop_errors(result: dict) -> dict[str, list[float]]:
    """Per commanded joint: measured minus commanded angle (deg) at each pose."""
    errors: dict[str, list[float]] = {}
    for pose in (result.get("data") or {}).get("poses") or []:
        measured = pose.get("measured") or {}
        for joint, target in (pose.get("commanded") or {}).items():
            if _finite(target) and _finite(measured.get(joint)):
                errors.setdefault(joint, []).append(measured[joint] - target)
    return errors


def judge_loop(main: dict, branch: dict) -> tuple[list[Metric], list[str]]:
    main_err, branch_err = loop_errors(main), loop_errors(branch)
    metrics, problems = [], []
    for joint in sorted(set(main_err) | set(branch_err)):
        m = max((abs(e) for e in main_err.get(joint, [])), default=None)
        b = max((abs(e) for e in branch_err.get(joint, [])), default=None)
        ok = (m is not None and b is not None and m <= REACH_TOL_DEG and b <= REACH_TOL_DEG
              and abs(b - m) <= SAME_ERROR_TOL_DEG)
        if not ok:
            problems.append(joint)
        metrics.append(Metric(f"{joint} largest error", _round(b), "deg", main=_round(m), ok=ok))
    return metrics, problems


@register("compare_joint_loop")
def compare_joint_loop(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    params = ctx.step.params or {}
    args = _args(ctx, **{k: params[k] for k in ("joints", "delta_deg", "hold_s") if k in params})
    results = {}
    with _released(ctx):
        for i, side in enumerate(SIDES):
            ctx.progress(i / 2, f"joint loop with {side}'s orca_core")
            results[side] = _run(ctx, side, "joint_loop", args, ctx.out_dir / side)
    failed = _failed_runs(ctx, results)
    if failed:
        return failed
    metrics, problems = judge_loop(results["main"], results["branch"])
    details = {"runs": {s: _brief(ctx, r) for s, r in results.items()},
               "loop_stats": {s: (results[s].get("data") or {}).get("loop_stats") for s in SIDES}}
    if not metrics:
        return CheckResult("error", "No encoder readings for the commanded joints", details=details)
    out = []
    for side in SIDES:
        errors = loop_errors(results[side])
        joints = sorted(errors)
        out.append(series("largest error per joint", list(range(len(joints))),
                          [max(abs(e) for e in errors[j]) for j in joints], side,
                          x_label="joint (alphabetical)", y_label="deg"))
    details["joint_order"] = sorted(loop_errors(results["branch"]))
    rule = f"within {REACH_TOL_DEG:g}° on both, errors within {SAME_ERROR_TOL_DEG:g}° of each other"
    summary = (f"Every commanded joint reached its angle {rule}" if not problems
               else f"Not {rule}: " + ", ".join(problems))
    status, summary = _mock_caveat(ctx, "fail" if problems else "pass", summary, "encoder angles")
    return CheckResult(status, summary, metrics=metrics, series=out, details=details)


# ----- tactile health ---------------------------------------------------------------------------


def tactile_summary(result: dict) -> dict:
    data = result.get("data") or {}
    connected = ((data.get("configuration") or {}).get("connected") or {})
    health = data.get("fingertip_health")
    erroring = None
    if isinstance(health, dict):
        erroring = sorted(f for f, h in health.items()
                          if isinstance(h, dict) and (h.get("error_code") or 0) != 0)
    link = data.get("link_health") or {}
    frames = data.get("frames_ok")
    duration = data.get("duration_s") or 0
    return {
        "active": sorted(f for f, on in connected.items() if on),
        "erroring": erroring,
        "frames": frames,
        "rate_hz": (frames / duration) if _finite(frames) and duration else None,
        "readings": data.get("distinct_readings") or 0,
        "link_ok": bool(link) and not link.get("port_dead"),
    }


@register("compare_tactile_health")
def compare_tactile_health(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    duration = float((ctx.step.params or {}).get("duration_s", 3.0))
    results = {}
    with _released(ctx):
        for i, side in enumerate(SIDES):
            ctx.progress(i / 2, f"tactile health with {side}'s orca_core")
            results[side] = _run(ctx, side, "tactile_health", _args(ctx, duration_s=duration),
                                 ctx.out_dir / side)
    failed = _failed_runs(ctx, results)
    if failed:
        return failed
    s = {side: tactile_summary(results[side]) for side in SIDES}
    live = {side: (s[side]["frames"] or 0) > 0 or s[side]["readings"] > 0 for side in SIDES}
    metrics = [
        Metric("active fingertips", _text(s["branch"]["active"]), main=_text(s["main"]["active"]),
               ok=s["branch"]["active"] == s["main"]["active"]),
        Metric("fingertips reporting an error",
               _text(s["branch"]["erroring"]) if s["branch"]["erroring"] is not None else "not reported",
               main=_text(s["main"]["erroring"]) if s["main"]["erroring"] is not None else "not reported",
               ok=s["branch"]["erroring"] == s["main"]["erroring"]),
        Metric("frames per second", _round(s["branch"]["rate_hz"], 1), "Hz",
               main=_round(s["main"]["rate_hz"], 1), ok=live["branch"] and live["main"]),
        Metric("link healthy", _text(s["branch"]["link_ok"]), main=_text(s["main"]["link_ok"]),
               ok=s["branch"]["link_ok"] and s["main"]["link_ok"]),
    ]
    differ = [m.name for m in metrics if m.ok is False]
    summary = ("Same sensor health on both, and live data arrives on both" if not differ
               else "Differs or fails: " + ", ".join(differ))
    status, summary = _mock_caveat(ctx, "fail" if differ else "pass", summary, "tactile frames")
    return CheckResult(status, summary, metrics=metrics,
                       details={"summary": s,
                                "runs": {side: _brief(ctx, r) for side, r in results.items()}})


# ----- script flags -----------------------------------------------------------------------------


FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def help_flags(text: str) -> set[str]:
    return set(FLAG_RE.findall(text or ""))


def script_report(ctx: CheckContext, side: str) -> dict:
    """Per script: whether ``--help`` runs, the shared flags it advertises, and for the
    non-interactive ones whether a ``--mock`` run works with ``--hardware-version`` in effect."""
    runner = ctx.sides
    report = {}
    scripts = runner.scripts(side)
    for i, script in enumerate(scripts):
        ctx.check_stop()
        ctx.progress((SIDES.index(side) + i / max(len(scripts), 1)) / 2,
                     f"{side}: {script} --help")
        folder = ctx.out_dir / side / Path(script).stem
        helped = runner.run_script(side, script, ["--help"], folder / "help",
                                   timeout_s=SCRIPT_TIMEOUT_S)
        entry = {"help_ok": helped["returncode"] == 0 and not helped["timed_out"],
                 "shared_flags": sorted(help_flags(helped["stdout"]) & set(SHARED_FLAGS))}
        if script in MOCK_RUN_SCRIPTS and "--mock" in entry["shared_flags"]:
            entry["mock_run"] = mock_run(ctx, side, script, folder / "mock")
        report[script] = entry
    return report


def mock_run(ctx: CheckContext, side: str, script: str, folder: Path) -> dict:
    config = ctx.sides.prepare_config(side, folder)
    ran = ctx.sides.run_script(side, script, [str(config), "--mock", "--hardware-version",
                                              str(SCRIPT_PIN)], folder,
                               timeout_s=SCRIPT_TIMEOUT_S)
    local = config.parent / "local_config.yaml"
    pinned = None
    if local.is_file():
        match = re.search(r"^hardware_version:\s*(\d+)", local.read_text(), re.MULTILINE)
        pinned = int(match.group(1)) if match else None
    return {"ok": ran["returncode"] == 0 and not ran["timed_out"],
            "returncode": ran["returncode"], "timed_out": ran["timed_out"],
            "mock_loaded": "Loaded Mock" in ran["stdout"],
            "pin_written": three_digit(pinned) == three_digit(SCRIPT_PIN),
            "output_tail": (ran["stdout"] + ran["stderr"])[-800:]}


def _script_text(entry: Optional[dict]) -> str:
    if entry is None:
        return "missing"
    parts = ["starts" if entry["help_ok"] else "does not start"]
    if entry["shared_flags"]:
        parts.append(" ".join(entry["shared_flags"]))
    run = entry.get("mock_run")
    if run:
        effects = run["ok"] and run["mock_loaded"] and run["pin_written"]
        parts.append("mock run ok" if effects else
                     f"mock run {'failed' if not run['ok'] else 'without the flags taking effect'}")
    return "; ".join(parts)


def judge_scripts(main: dict, branch: dict) -> tuple[list[Metric], list[str]]:
    metrics, problems = [], []
    for script in sorted(set(main) | set(branch)):
        m, b = main.get(script), branch.get(script)
        why = []
        if m is not None and m["help_ok"]:
            if b is None or not b["help_ok"]:
                why.append("does not start")
            else:
                lost = set(m["shared_flags"]) - set(b["shared_flags"])
                if lost:
                    why.append("lost " + ", ".join(sorted(lost)))
                mr, br = m.get("mock_run"), b.get("mock_run")
                if mr and mr["ok"] and mr["mock_loaded"] and mr["pin_written"]:
                    if not (br and br["ok"] and br["mock_loaded"] and br["pin_written"]):
                        why.append("mock run fails or ignores its flags")
        if why:
            problems.append(f"{script} ({', '.join(why)})")
        metrics.append(Metric(script, _script_text(b), main=_script_text(m), ok=not why))
    return metrics, problems


@register("compare_script_flags")
def compare_script_flags(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, SIDES)
    if missing:
        return missing
    if not all(callable(getattr(ctx.sides, n, None)) for n in ("scripts", "run_script", "prepare_config")):
        return CheckResult("error", "The side runner cannot run orca_core scripts")
    reports = {side: script_report(ctx, side) for side in SIDES}
    metrics, problems = judge_scripts(reports["main"], reports["branch"])
    summary = ("Every script that starts on main starts on the branch, with the same shared "
               "flags taking effect" if not problems else "Broken on the branch: " + "; ".join(problems))
    return CheckResult("fail" if problems else "pass", summary, metrics=metrics,
                       details={"scripts": reports, "shared_flags": list(SHARED_FLAGS),
                                "mock_run_scripts": list(MOCK_RUN_SCRIPTS)})


# ----- branch-only: calibration travel ----------------------------------------------------------


def _events(result: dict, joint: Optional[str] = None, names: Iterable[str] = ()) -> list[dict]:
    names = set(names)
    return [e for e in result.get("events") or []
            if (not names or e.get("event") in names)
            and (joint is None or e.get("joint") in (None, joint))]


def _saved_limits(result: dict, joint: str) -> bool:
    data = result.get("data") or {}
    motor = None
    for m, j in (data.get("joint_by_motor") or {}).items():
        if j == joint:
            motor = m
    saved = ((data.get("saved") or {}).get("motor_limits") or {}).get(str(motor))
    return isinstance(saved, list) and len(saved) == 2 and all(_finite(v) for v in saved)


TRAVEL_EVENTS = ("travel_checked", "travel_excess", "travel_retry_started",
                 "travel_retry_succeeded", "travel_retry_exhausted", "travel_retry_skipped",
                 "travel_retry_unavailable", "travel_retry_disabled", "travel_baseline_missing")


def judge_redrive(result: dict, joint: str) -> tuple[str, str, list[Metric], list[Series]]:
    """``(status, summary, metrics, series)`` for one joint's calibration under a tight margin."""
    events = _events(result, joint, TRAVEL_EVENTS)
    checked = [e for e in events if e["event"] == "travel_checked"]
    data = result.get("data") or {}
    saved = _saved_limits(result, joint)
    outcome = data.get("outcome")
    if outcome != "done":
        return "fail", f"Calibration ended {outcome}", [], []
    if not checked:
        hand = result.get("hand") or {}
        why = ("the branch did not treat the hand as v2.1 "
               f"(hardware_version {hand.get('hardware_version')})"
               if hand.get("uses_motor_travel") is False else "no travel_checked event")
        return "fail", f"Travel was not checked: {why}", [], []
    first = checked[0]
    travel, expected = first.get("travel_deg"), first.get("expected_deg")
    low, high = (first.get("bounds_deg") or [None, None])[:2]
    retries = [e for e in events if e["event"] == "travel_retry_started"]
    ends = [e["event"] for e in events if e["event"] in (
        "travel_retry_succeeded", "travel_retry_exhausted", "travel_retry_skipped",
        "travel_retry_unavailable", "travel_retry_disabled")]
    attempts = retries[0].get("attempts") if retries else None
    currents = [e.get("current") for e in retries]
    final = travel
    if "travel_retry_succeeded" in ends or "travel_retry_exhausted" in ends:
        last = [e for e in events if e["event"] in ("travel_retry_succeeded", "travel_retry_exhausted")]
        final = last[-1].get("travel_deg", travel)
    metrics = [
        Metric("first-pass travel", _round(travel), "deg"),
        Metric("baseline", _round(expected), "deg"),
        Metric("margin band", f"{_round(low)} – {_round(high)}", "deg"),
        Metric("re-drives", len(retries), main=None,
               ok=None if attempts is None else len(retries) <= attempts),
        Metric("re-drive currents", _text([_round(c, 0) for c in currents]) if currents else "none", "mA"),
        Metric("final travel", _round(final), "deg"),
        Metric("calibration saved", _text(saved), ok=saved),
    ]
    attempts_series = [series("travel per attempt", [0], [travel], "branch",
                              x_label="attempt (0 = first pass)", y_label="deg")] if _finite(travel) else []
    if not saved:
        return "fail", "The joint's limits were not saved to calibration.yaml", metrics, attempts_series
    if first.get("within_margin"):
        return ("skipped", f"Inconclusive: travel {travel:.1f}° is within the margin of the "
                f"{expected:.1f}° baseline, so the re-drive was not exercised",
                metrics, attempts_series)
    if _finite(high) and _finite(travel) and travel > high:
        if retries:
            return "fail", "Travel past the baseline was re-driven, which cannot shorten it", metrics, attempts_series
        return ("skipped", f"Inconclusive: travel {travel:.1f}° is past the baseline; it is reported, "
                "not re-driven, so the re-drive was not exercised", metrics, attempts_series)
    if not retries:
        reason = ends[0] if ends else "no re-drive event"
        return "fail", f"Travel {travel:.1f}° is short of the margin but was not re-driven ({reason})", metrics, attempts_series
    problems = []
    if attempts is not None and len(retries) > attempts:
        problems.append(f"{len(retries)} re-drives, more than the {attempts} configured")
    if any(not _finite(c) for c in currents) or any(b < a for a, b in zip(currents, currents[1:])):
        problems.append("re-drive currents went down")
    if not ends:
        problems.append("no re-drive outcome was reported")
    elif ends[-1] not in ("travel_retry_succeeded", "travel_retry_exhausted"):
        problems.append(f"the re-drive ended {ends[-1].removeprefix('travel_retry_')}")
    if _finite(travel) and _finite(final):
        attempts_series = [series("travel per attempt", [0, len(retries)], [travel, final], "branch",
                                  x_label="attempt (0 = first pass)", y_label="deg")]
    if problems:
        return "fail", "; ".join(problems), metrics, attempts_series
    summary = (f"Short travel {travel:.1f}° of {expected:.1f}° was re-driven {len(retries)} time(s) "
               f"at {_text([_round(c, 0) for c in currents])} mA, ending "
               f"{ends[-1].removeprefix('travel_retry_')} at {final:.1f}°; calibration saved")
    return "pass", summary, metrics, attempts_series


REDRIVE_STRETCH = 1.2
"""The picked joint's baseline in the copy, as a multiple of its last measured travel: short on any hand."""
REDRIVE_FALLBACK_STRETCH = 3.0
"""The same, as a multiple of its baseline, when the hand has no measured travel yet."""


def _yaml_file(path: Optional[Path]) -> dict:
    try:
        return (yaml.safe_load(Path(path).read_text()) or {}) if path else {}
    except (OSError, yaml.YAMLError):
        return {}


def pick_redrive_joint(measured: dict, per_hand: dict, shared: dict,
                       wanted: Optional[str] = None) -> tuple[Optional[str], Optional[float], str]:
    """``(joint, baseline to write, why)``: the finger joint measured shortest against its
    effective baseline (the hand's own ``joint_motor_travel`` wins over the shared v2.1 one),
    with a baseline that makes it short whatever the hand."""
    baselines = {j: v for j, v in {**shared, **per_hand}.items() if j != "wrist" and _finite(v) and v > 0}
    if wanted:
        if wanted == "wrist" or wanted not in baselines:
            return None, None, f"{wanted} has no finger baseline to re-drive against"
        baselines = {wanted: baselines[wanted]}
    ratios = {j: measured[j] / b for j, b in baselines.items() if _finite(measured.get(j))}
    if ratios:
        joint = min(ratios, key=ratios.get)
        return (joint, round(REDRIVE_STRETCH * measured[joint], 1),
                f"{joint} measured {measured[joint]:.1f}° against its {baselines[joint]:g}° baseline "
                f"({ratios[joint] - 1:+.0%}), the shortest; its baseline in the copy is "
                f"{REDRIVE_STRETCH:g}× that measurement")
    if not baselines:
        return None, None, "no finger joint has a travel baseline"
    joint = sorted(baselines)[0]
    return (joint, round(REDRIVE_FALLBACK_STRETCH * baselines[joint], 1),
            f"no measured travel on this hand yet; {joint}'s baseline in the copy is "
            f"{REDRIVE_FALLBACK_STRETCH:g}× its {baselines[joint]:g}° baseline")


@register("calibration_redrive")
def calibration_redrive(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, ("branch",))
    if missing:
        return missing
    params = ctx.step.params or {}
    margin = float(params.get("margin", 0.01))
    console = getattr(ctx.sides, "console_config", lambda: None)()
    calibration = _yaml_file(Path(console).parent / "calibration.yaml" if console else None)
    source = _yaml_file(ctx.sides.config_source("branch")[0])
    per_hand = dict(source.get("joint_motor_travel") or {})
    joint, baseline, why = pick_redrive_joint(calibration.get("motor_travel_measured") or {}, per_hand,
                                              source.get("joint_motor_travel_v21") or {},
                                              params.get("joint"))
    if joint is None:
        return CheckResult("error", f"Not run: {why}")
    overrides = {"calibration_travel_margin": margin,
                 "joint_motor_travel": {**per_hand, joint: baseline}}
    ctx.progress(0.0, f"calibrating {joint} against a {baseline:g}° baseline")
    result = _run(ctx, "branch", "calibrate", _args(ctx, joints=[joint], config_overrides=overrides),
                  ctx.out_dir / "branch")
    failed = _failed_runs(ctx, {"branch": result})
    if failed:
        return failed
    status, summary, metrics, out = judge_redrive(result, joint)
    return CheckResult(status, f"{summary}. Picked: {why}", metrics=metrics, series=out,
                       details={"joint": joint, "margin": margin, "baseline_written": baseline,
                                "why": why, "travel_events": _events(result, joint, TRAVEL_EVENTS),
                                "run": _brief(ctx, result)})


def judge_plain_pass(result: dict, joint: str) -> tuple[str, str, list[Metric]]:
    data = result.get("data") or {}
    travel = _events(result, joint, TRAVEL_EVENTS)
    steps = [e.get("index") for e in _events(result, None, ("step_started",))]
    repeated = len(steps) != len(set(steps))
    retries = [e for e in travel if e["event"].startswith("travel_retry")]
    saved = _saved_limits(result, joint)
    metrics = [
        Metric("hardware version in force", _text((result.get("hand") or {}).get("hardware_version"))),
        Metric("travel events", len(travel), ok=not travel),
        Metric("re-drives", len(retries), ok=not retries),
        Metric("steps run", len(steps), ok=not repeated),
        Metric("calibration saved", _text(saved), ok=saved),
    ]
    if data.get("outcome") != "done":
        return "fail", f"Calibration ended {data.get('outcome')}", metrics
    problems = [m.name for m in metrics if m.ok is False]
    if problems:
        return "fail", "Not a single plain pass: " + ", ".join(problems), metrics
    return "pass", f"One plain pass over {len(steps)} step(s), no travel check, no re-drive; saved", metrics


@register("calibration_plain_pass")
def calibration_plain_pass(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, ("branch",))
    if missing:
        return missing
    joint = (ctx.step.params or {}).get("joint", "index_mcp")
    ctx.progress(0.0, f"calibrating {joint} pinned to v2.0")
    result = _run(ctx, "branch", "calibrate",
                  _args(ctx, joints=[joint], config_overrides={"hardware_version": V20}),
                  ctx.out_dir / "branch")
    failed = _failed_runs(ctx, {"branch": result})
    if failed:
        return failed
    status, summary, metrics = judge_plain_pass(result, joint)
    return CheckResult(status, summary, metrics=metrics,
                       details={"joint": joint, "events": result.get("events") or [],
                                "run": _brief(ctx, result)})


# ----- branch-only: hardware version pin --------------------------------------------------------


def _digests(folder: Optional[Path]) -> dict:
    from orca_ui.hardware_tests.sides import file_digest

    if folder is None:
        return {}
    return {name: file_digest(folder / name) for name in ("config.yaml", "local_config.yaml")}


def judge_pin(result: dict, pin: int, board: int,
              unchanged: Optional[bool]) -> tuple[str, str, list[Metric]]:
    """``unchanged`` is ``None`` when the packaged config could not be located to compare."""
    in_force = three_digit((result.get("data") or {}).get("hardware_version"))
    warnings = [r.get("message", "") for r in result.get("log") or []
                if "hardware_version" in r.get("message", "")]
    named = [w for w in warnings
             if re.search(rf"\b{pin}\b", w) and re.search(rf"\b{board}\b", w)]
    metrics = [
        Metric("version in force", in_force, ok=in_force == pin),
        Metric("pinned", pin), Metric("board", board),
        Metric("warning names both", named[0] if named else (warnings[0] if warnings else "none"),
               ok=bool(named)),
        Metric("packaged config unchanged",
               _text(unchanged) if unchanged is not None else "could not be checked", ok=unchanged),
    ]
    problems = [m.name for m in metrics if m.ok is False]
    if problems:
        return "fail", "Not as specified: " + ", ".join(problems), metrics
    return "pass", f"The pin {pin} wins over the board's {board}, a warning names both, and the packaged config is unchanged", metrics


@register("hardware_version_pin")
def hardware_version_pin(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, ("branch",))
    if missing:
        return missing
    board = three_digit(ctx.hand.hardware_version) if ctx.hand.hardware_version_source == "board" else None
    note = None
    if board is None:
        board = V21
        note = (f"the console has no board-reported version, so {board} stands in for the board's "
                "value (it reaches orca_core the same way)")
    pin = V20 if board // 10 == V21 // 10 else V21
    packaged = console_dir = None
    with contextlib.suppress(Exception):
        packaged = ctx.sides.config_source("branch")[0].parent
    with contextlib.suppress(Exception):
        console_dir = ctx.sides.console_config().parent
    before = {"packaged": _digests(packaged), "console": _digests(console_dir)}
    result = _run(ctx, "branch", "load_config",
                  _args(ctx, detected_hardware_version=board,
                        config_overrides={"hardware_version": pin}),
                  ctx.out_dir / "branch")
    after = {"packaged": _digests(packaged), "console": _digests(console_dir)}
    failed = _failed_runs(ctx, {"branch": result})
    if failed:
        return failed
    status, summary, metrics = judge_pin(result, pin, board,
                                         before == after if packaged is not None else None)
    if note:
        summary += f" ({note})"
    return CheckResult(status, summary, metrics=metrics,
                       details={"digests_before": before, "digests_after": after, "note": note,
                                "run": _brief(ctx, result)})


# ----- branch-only: guided tensioning gate ------------------------------------------------------


def judge_gate(result: dict) -> tuple[str, str, list[Metric]]:
    attempts = {bool(a.get("any_hardware")): a for a in (result.get("data") or {}).get("attempts") or []}
    plain, override = attempts.get(False) or {}, attempts.get(True) or {}
    refused = plain.get("outcome") == "refused" and bool(plain.get("message"))
    started = override.get("outcome") == "started"
    metrics = [
        Metric("pinned to v2.0", plain.get("outcome"), ok=refused),
        Metric("refusal message", plain.get("message") or "none"),
        Metric("with the any-hardware override", override.get("outcome"), ok=started),
        Metric("first prompt", ((override.get("first_prompt") or {}).get("action")) or "none"),
    ]
    if refused and started:
        return "pass", f"Refused on v2.0 (“{plain['message']}”) and started with the override", metrics
    problems = []
    if not refused:
        problems.append(f"pinned to v2.0 it {plain.get('outcome') or 'did not run'}")
    if not started:
        problems.append(f"with the override it {override.get('outcome') or 'did not run'}"
                        + (f": {override.get('message')}" if override.get("message") else ""))
    return "fail", "; ".join(problems), metrics


@register("guided_tension_refusal")
def guided_tension_refusal(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, ("branch",))
    if missing:
        return missing
    ctx.progress(0.0, "starting guided tensioning pinned to v2.0")
    result = _run(ctx, "branch", "guided_tension_gate",
                  _args(ctx, any_hardware=[False, True],
                        config_overrides={"hardware_version": V20}),
                  ctx.out_dir / "branch")
    failed = _failed_runs(ctx, {"branch": result})
    if failed:
        return failed
    status, summary, metrics = judge_gate(result)
    return CheckResult(status, summary, metrics=metrics,
                       details={"attempts": (result.get("data") or {}).get("attempts"),
                                "run": _brief(ctx, result)})


# ----- branch-only: calibration against the encoders --------------------------------------------


def encoder_stops(result: dict) -> list[dict]:
    """Per encoder-measured joint: the config ROM against the ROM the encoders measured."""
    data = result.get("data") or {}
    measured = (data.get("calibration") or {}).get("joint_roms_measured_dict") or {}
    config = (result.get("hand") or {}).get("joint_roms_dict") or {}
    rows = []
    for joint in sorted(measured):
        m, c = measured[joint], config.get(joint)
        if not (isinstance(m, list) and len(m) == 2 and all(_finite(v) for v in m)):
            continue
        row = {"joint": joint, "measured": m, "config": c}
        if isinstance(c, list) and len(c) == 2 and all(_finite(v) for v in c):
            row["lower_diff"] = m[0] - c[0]
            row["span_diff"] = (m[1] - m[0]) - (c[1] - c[0])
        rows.append(row)
    return rows


@register("calibration_vs_encoders")
def calibration_vs_encoders(ctx: CheckContext) -> CheckResult:
    missing = _need_sides(ctx, ("branch",))
    if missing:
        return missing
    if ctx.hand.mock:
        return CheckResult("skipped", "The mock hand has no encoder stream for calibration's encoder pass")
    ctx.progress(0.0, "calibrating while recording the joint encoders")
    result = _run(ctx, "branch", "calibrate", _args(ctx, encoders=True), ctx.out_dir / "branch")
    failed = _failed_runs(ctx, {"branch": result})
    if failed:
        return failed
    data = result.get("data") or {}
    details = {"run": _brief(ctx, result),
               "anchor_events": _events(result, None, ("encoder_anchor_recorded",
                                                        "encoder_anchor_failed"))}
    if not data.get("encoder_pass"):
        return CheckResult("error", "Calibration ran without an encoder pass", details=details)
    rows = encoder_stops(result)
    details["stops"] = rows
    failed_anchors = [e.get("joint") for e in details["anchor_events"]
                      if e.get("event") == "encoder_anchor_failed"]
    metrics = [Metric(f"{r['joint']} measured span − config span", _round(r.get("span_diff")), "deg")
               for r in rows]
    metrics.append(Metric("anchors that failed", _text(failed_anchors) if failed_anchors else "none"))
    joints = [r["joint"] for r in rows if _finite(r.get("span_diff"))]
    out = [series("measured span − config span", list(range(len(joints))),
                  [r["span_diff"] for r in rows if _finite(r.get("span_diff"))], "branch",
                  x_label="joint (alphabetical)", y_label="deg")] if joints else []
    details["joint_order"] = joints
    widest = max(rows, key=lambda r: abs(r.get("span_diff") or 0), default=None)
    summary = (f"{len(rows)} joint(s) measured by the encoders"
               + (f"; largest difference {widest['joint']} {widest['span_diff']:+.1f}°"
                  if widest and _finite(widest.get("span_diff")) else ""))
    return CheckResult("observed", summary, metrics=metrics, series=out, details=details)

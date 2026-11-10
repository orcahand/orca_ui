"""Hardware tests: the decisions the main-vs-branch and branch-only checks make,
fed with synthetic recorder results."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

from orca_ui.hardware_tests.checks import compare
from orca_ui.hardware_tests.checks.base import get_check
from orca_ui.hardware_tests.model import HandFacts, Step


def test_downsample_keeps_at_most_2000_points_and_the_peaks():
    x = list(range(10_000))
    y = [math.sin(i / 50) for i in x]
    y[4321] = 99.0
    xs, ys = compare.downsample(x, y)
    assert len(xs) == len(ys) <= compare.MAX_POINTS
    assert 99.0 in ys and xs == sorted(xs)
    assert compare.series("s", [0, 1, None], [1, float("nan"), 2], "main").x == [0]


def _neutral(cycles: list[dict]) -> dict:
    return {"ok": True, "data": {"cycles": [{"motor_pos": c} for c in cycles],
                                 "joint_by_motor": {"3": "index_mcp"}}}


def test_neutral_must_land_within_mains_repeatability():
    main = _neutral([{"3": 0.500}, {"3": 0.520}])
    near = _neutral([{"3": 0.530}])
    metrics, outside = compare.judge_neutral(main, near)
    assert outside == [] and metrics[0].ok and metrics[0].main == round(math.degrees(0.51), 2)
    far = _neutral([{"3": 0.600}])
    metrics, outside = compare.judge_neutral(main, far)
    assert outside == ["index_mcp (motor 3)"] and metrics[0].ok is False
    # A perfectly repeatable main still allows the noise floor.
    metrics, outside = compare.judge_neutral(_neutral([{"3": 0.5}]), _neutral([{"3": 0.5 + math.radians(0.9)}]))
    assert outside == []


def _calibration(limits: dict, travel: dict) -> dict:
    return {"ok": True, "data": {"outcome": "done", "joint_by_motor": {"3": "index_mcp"},
                                 "calibration": {"motor_limits_dict": limits,
                                                 "motor_travel_measured_dict": travel}}}


def test_plain_calibration_limits_must_lie_within_mains_spread():
    main = [_calibration({"3": [-1.00, 1.00]}, {"index_mcp": 114.0}),
            _calibration({"3": [-1.10, 1.02]}, {"index_mcp": 120.0})]
    inside = _calibration({"3": [-1.05, 1.01]}, {"index_mcp": 117.0})
    metrics, outside = compare.judge_calibration(main, inside)
    assert outside == []
    assert [m.name for m in metrics] == ["index_mcp (motor 3) lower limit",
                                         "index_mcp (motor 3) upper limit", "index_mcp travel"]
    assert metrics[2].value == 117.0 and metrics[2].main == 117.0
    off = _calibration({"3": [-1.05, 1.50]}, {"index_mcp": 147.0})
    assert compare.judge_calibration(main, off)[1] == ["index_mcp (motor 3) upper limit"]


def test_plain_pass_never_swaps_a_v21_hands_joint_map(tmp_path):
    config = tmp_path / "config.yaml"
    sides = SimpleNamespace(config_source=lambda side: (config, "packaged"))
    config.write_text("joint_to_motor_map: {thumb_mcp: 15}\njoint_to_motor_map_v21: {thumb_mcp: -15}\n")
    assert compare.plain_pass_overrides(_ctx(tmp_path, sides))[0] == {"calibration_travel_retries": 0}
    config.write_text("joint_to_motor_map: {thumb_mcp: 15}\n")
    assert compare.plain_pass_overrides(_ctx(tmp_path, sides))[0] == {"hardware_version": 200}


def test_tension_hold_compares_current_and_motion_per_motor():
    result = {"hand": {"motor_ids": [3, 4]}, "data": {"hold_started_t": 1.0, "hold_ended_t": 5.0}}
    rows = [{"t": t / 10, "cur": [300.0, 200.0], "pos": [0.0, t / 1000]} for t in range(60)]
    profile = compare.hold_profile(result, rows)
    assert profile["current"] == {"3": 300.0, "4": 200.0}
    assert profile["drift"]["3"] == 0.0 and profile["drift"]["4"] > 0
    branch = {"current": {"3": 300.0, "4": 400.0}, "drift": {"3": 0.0, "4": profile["drift"]["4"]}}
    metrics, outside, mechanical, unjudged = compare.judge_hold([profile, profile], [branch], {"4": "index_abd"})
    assert outside == ["index_abd (motor 4) current in branch run 1"]
    assert len(metrics) == 4 and mechanical == [] and unjudged == []


def _hold(current: dict, stalls: dict) -> dict:
    return {"current": current, "drift": {}, "stalls": {"wind +": stalls}}


def test_a_tendon_that_wound_elsewhere_is_reported_not_failed_on_its_current():
    main = [_hold({"10": 37.0}, {"10": 356.0}), _hold({"10": 34.0}, {"10": 355.8}),
            _hold({"10": 36.0}, {"10": 356.1})]
    slipped = _hold({"10": 53.0}, {"10": 391.4})
    metrics, outside, mechanical, unjudged = compare.judge_hold(main, [slipped], {"10": "middle_mcp"})
    assert outside == [] and unjudged == ["middle_mcp (motor 10)"]
    assert mechanical == ["middle_mcp (motor 10) in branch run 1 (wind + stalled elsewhere)"]
    same = _hold({"10": 53.0}, {"10": 356.3})
    _, outside, mechanical, unjudged = compare.judge_hold(main, [slipped, same], {"10": "middle_mcp"})
    assert outside == ["middle_mcp (motor 10) current in branch run 2"] and unjudged == []


def test_mains_typical_spread_widens_a_motor_whose_runs_happened_to_agree():
    main = [_hold({"10": 37.0, "16": 56.0, "17": 65.0}, {}),
            _hold({"10": 34.0, "16": 25.0, "17": 81.0}, {})]
    # Motor 10's runs agree within 3 mA, but main's median spread across motors is 16 mA.
    branch = _hold({"10": 50.0, "16": 40.0, "17": 70.0}, {})
    _, outside, *_ = compare.judge_hold(main, [branch], {})
    assert outside == []
    _, outside, *_ = compare.judge_hold(main, [_hold({"10": 70.0, "16": 40.0, "17": 70.0}, {})], {})
    assert outside == ["motor 10 current in branch run 1"]


def test_runs_alternate_between_the_sides():
    assert compare.interleaved_plan(3, 2) == [("main", "main run 1"), ("branch", "branch run 1"),
                                               ("main", "main run 2"), ("branch", "branch run 2"),
                                               ("main", "main run 3")]
    assert [s for s, _ in compare.interleaved_plan(2, 1)] == ["main", "branch", "main"]


def test_wind_stalls_are_where_each_pass_ended():
    result = {"hand": {"motor_ids": [10]}, "events": [
        {"event": "winding_progress", "t": 0.2}, {"event": "winding_progress", "t": 4.0},
        {"event": "phase", "phase": "ramp", "t": 8.0}]}
    rows = [{"t": t / 10, "pos": [math.radians(t)]} for t in range(100)]
    stalls = compare.wind_stalls(result, rows)
    assert stalls["wind -"]["10"] == 39.0 and stalls["wind +"]["10"] == 79.0


def _events(*events) -> list[dict]:
    return [dict(e) for e in events]


def _redrive(events, *, saved=True, outcome="done") -> dict:
    return {"ok": True, "events": events, "hand": {"uses_motor_travel": True},
            "data": {"outcome": outcome, "joint_by_motor": {"3": "index_mcp"},
                     "saved": {"motor_limits": {"3": [-1.0, 1.0] if saved else [None, None]}}}}


CHECKED_SHORT = {"event": "travel_checked", "joint": "index_mcp", "travel_deg": 110.0,
                 "expected_deg": 122.0, "bounds_deg": [120.8, 123.2], "within_margin": False}


def test_redrive_decision():
    within = dict(CHECKED_SHORT, travel_deg=121.5, within_margin=True)
    status, summary, *_ = compare.judge_redrive(_redrive(_events(within)), "index_mcp")
    assert status == "skipped" and "not exercised" in summary
    long = dict(CHECKED_SHORT, travel_deg=138.3)
    status, summary, *_ = compare.judge_redrive(_redrive(_events(long)), "index_mcp")
    assert status == "skipped" and "past the baseline" in summary

    retries = [{"event": "travel_retry_started", "joint": "index_mcp", "attempt": n, "attempts": 3,
                "current": 900.0 + 50 * n} for n in (1, 2)]
    done = {"event": "travel_retry_succeeded", "joint": "index_mcp", "travel_deg": 121.0}
    status, summary, metrics, series = compare.judge_redrive(
        _redrive(_events(CHECKED_SHORT, *retries, done)), "index_mcp")
    assert status == "pass", summary
    assert series[0].y == [110.0, 121.0]

    assert compare.judge_redrive(_redrive(_events(CHECKED_SHORT)), "index_mcp")[0] == "fail"
    too_many = [dict(r, attempts=1) for r in retries]
    assert compare.judge_redrive(_redrive(_events(CHECKED_SHORT, *too_many, done)), "index_mcp")[0] == "fail"
    lower = [dict(retries[0], current=950.0), dict(retries[1], current=900.0)]
    assert compare.judge_redrive(_redrive(_events(CHECKED_SHORT, *lower, done)), "index_mcp")[0] == "fail"
    exhausted = {"event": "travel_retry_exhausted", "joint": "index_mcp", "travel_deg": 112.0}
    assert compare.judge_redrive(_redrive(_events(CHECKED_SHORT, *retries, exhausted)), "index_mcp")[0] == "pass"
    skipped = {"event": "travel_retry_skipped", "joint": "index_mcp"}
    assert compare.judge_redrive(_redrive(_events(CHECKED_SHORT, *retries, skipped)), "index_mcp")[0] == "fail"
    unsaved = _redrive(_events(CHECKED_SHORT, *retries, done), saved=False)
    assert compare.judge_redrive(unsaved, "index_mcp")[0] == "fail"
    nothing_checked = _redrive([])
    nothing_checked["hand"]["uses_motor_travel"] = False
    status, summary, *_ = compare.judge_redrive(nothing_checked, "index_mcp")
    assert status == "fail" and "v2.1" in summary


def test_the_redrive_joint_is_the_shortest_and_made_short_on_any_hand():
    measured = {"index_abd": 35.68, "index_mcp": 138.25, "thumb_cmc": 57.92, "wrist": 120.0}
    shared = {"index_abd": 43, "index_mcp": 122, "thumb_cmc": 59, "wrist": 156}
    joint, baseline, why = compare.pick_redrive_joint(measured, {}, shared)
    assert joint == "index_abd" and baseline == round(1.2 * 35.68, 1) and "-17%" in why
    # The hand's own baseline wins over the shared one.
    joint, *_ = compare.pick_redrive_joint(measured, {"thumb_cmc": 80}, shared)
    assert joint == "thumb_cmc"
    assert compare.pick_redrive_joint(measured, {}, shared, "wrist")[0] is None
    joint, baseline, why = compare.pick_redrive_joint({}, {}, shared)
    assert joint == "index_abd" and baseline == 129.0 and "no measured travel" in why


def _mapped(roms) -> dict:
    return {"ok": True, "data": {"mapping": {"joint_roms": roms, "joint_to_motor_map": {"index_pip": 2},
                                              "joint_inversion": {}, "neutral_position": {"index_pip": 30}},
                                 "targets": {"2": 1.0},
                                 "cycles": [{"motor_pos": {"2": 1.0 + math.radians(0.4)}}]}}


def test_neutral_is_inconclusive_when_the_sides_map_joints_differently():
    same = _mapped({"index_pip": [-15, 107]})
    assert compare.mapping_difference(same, _mapped({"index_pip": [-15.0, 107.0]})) == []
    assert compare.mapping_difference(same, _mapped({"index_pip": [-9.01, 106.43]})) == ["joint_roms"]
    assert compare.mapping_difference(same, {"ok": True, "data": {}}) == ["a side did not report the mapping it used"]
    assert round(compare.tracking_errors(same)["2"], 3) == 0.4


def test_neutral_takes_the_mapping_from_the_consoles_config(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("joint_roms: {index_pip: [-15, 107]}\nneutral_position: {index_pip: 30}\nmax_current: default\n")
    sides = SimpleNamespace(console_config=lambda: config)
    overrides, overlay = compare.mapping_overrides(_ctx(tmp_path, sides))
    assert overrides == {"joint_roms": {"index_pip": [-15, 107]}, "neutral_position": {"index_pip": 30}}
    assert overlay == {"source": str(config), "fields": ["joint_roms", "neutral_position"]}


def test_plain_pass_has_no_travel_check():
    steps = [{"event": "step_started", "index": 0}, {"event": "step_started", "index": 1}]
    assert compare.judge_plain_pass(_redrive(steps), "index_mcp")[0] == "pass"
    assert compare.judge_plain_pass(_redrive(steps + [CHECKED_SHORT]), "index_mcp")[0] == "fail"


def test_pin_must_win_and_be_named_in_a_warning():
    result = {"data": {"hardware_version": 200}, "log": [
        {"message": "the config pins hardware_version=200 (config.yaml), so the detected 210 is not used."}]}
    assert compare.judge_pin(result, 200, 210, True)[0] == "pass"
    assert compare.judge_pin(dict(result, log=[]), 200, 210, True)[0] == "fail"
    assert compare.judge_pin(result, 200, 210, False)[0] == "fail"
    assert compare.judge_pin(dict(result, data={"hardware_version": 210}), 200, 210, True)[0] == "fail"
    assert compare.judge_pin({"data": {"hardware_version": 2}, "log": result["log"]}, 200, 210, True)[0] == "pass"


def test_guided_tension_gate_refuses_plainly_and_starts_with_the_override():
    refused = {"any_hardware": False, "outcome": "refused", "message": "needs v2.1 hardware"}
    started = {"any_hardware": True, "outcome": "started", "first_prompt": {"action": "pose"}}
    assert compare.judge_gate({"data": {"attempts": [refused, started]}})[0] == "pass"
    assert compare.judge_gate({"data": {"attempts": [dict(refused, outcome="started"), started]}})[0] == "fail"
    assert compare.judge_gate({"data": {"attempts": [refused, dict(started, outcome="refused")]}})[0] == "fail"


def test_scripts_must_keep_starting_and_keep_their_shared_flags():
    ok_run = {"ok": True, "mock_loaded": True, "pin_written": True}
    main = {"calibrate.py": {"help_ok": True, "shared_flags": ["--hardware-version", "--mock"],
                             "mock_run": ok_run},
            "detect.py": {"help_ok": True, "shared_flags": []},
            "old.py": {"help_ok": False, "shared_flags": []}}
    same = {k: dict(v) for k, v in main.items()}
    assert compare.judge_scripts(main, same)[1] == []
    lost = dict(same, **{"calibrate.py": {"help_ok": True, "shared_flags": ["--mock"], "mock_run": ok_run}})
    assert compare.judge_scripts(main, lost)[1] == ["calibrate.py (lost --hardware-version)"]
    ignored = dict(same, **{"calibrate.py": dict(main["calibrate.py"], mock_run=dict(ok_run, pin_written=False))})
    assert "mock run" in compare.judge_scripts(main, ignored)[1][0]
    gone = {k: v for k, v in same.items() if k != "detect.py"}
    assert compare.judge_scripts(main, gone)[1] == ["detect.py (does not start)"]


def test_joint_loop_needs_both_sides_on_target_with_the_same_error():
    def loop(err):
        return {"data": {"poses": [{"commanded": {"index_mcp": 10.0}, "measured": {"index_mcp": 10.0 + err}}]}}
    metrics, problems = compare.judge_loop(loop(0.5), loop(1.0))
    assert problems == [] and metrics[0].value == 1.0 and metrics[0].main == 0.5
    assert compare.judge_loop(loop(0.5), loop(2.5))[1] == ["index_mcp"]
    assert compare.judge_loop(loop(5.0), loop(5.0))[1] == ["index_mcp"]


class _Sides:
    def __init__(self, results: dict, unavailable: dict | None = None):
        self.results = results
        self.unavailable = unavailable or {}
        self.runs: list[tuple] = []

    def available(self, side):
        return self.unavailable.get(side)

    def run(self, side, scenario, args, out_dir):
        self.runs.append((side, scenario, Path(out_dir).name))
        return self.results[side]


def _ctx(tmp_path, sides, check="compare_detect", **params):
    hand = HandFacts(label="ser-0000", model_name="orcahand-right", motor_family=None,
                     hardware_version=210, hardware_version_source="board", side="right",
                     capabilities=(), mock=False)
    step = Step(id="B1", title="t", kind="compare", instructions="", pass_rule="", check=check,
                params=params)
    return SimpleNamespace(step=step, hand=hand, sides=sides, out_dir=tmp_path, service=None,
                           log=lambda line: None, progress=lambda f, d="": None,
                           check_stop=lambda: None, step_result=lambda s: None)


def test_compare_detect_puts_branch_and_main_side_by_side(tmp_path):
    found = {"model_name": "orcahand-right", "side": "right", "motor_type": "feetech",
             "motor_port": "/dev/cu.usbmodemXXXX", "has_tactile": False, "has_encoders": False}
    results = {s: {"ok": True, "available": True, "data": {"detection": dict(found)}} for s in ("main", "branch")}
    sides = _Sides(results)
    check = get_check("compare_detect")
    result = check(_ctx(tmp_path, sides))
    assert result.status == "pass"
    assert [r[0] for r in sides.runs] == ["main", "branch"]
    family = next(m for m in result.metrics if m.name == "motor family")
    assert (family.value, family.main, family.ok) == ("feetech", "feetech", True)

    results["branch"]["data"]["detection"]["side"] = "left"
    result = check(_ctx(tmp_path, _Sides(results)))
    assert result.status == "fail" and "side" in result.summary

    result = check(_ctx(tmp_path, _Sides(results, {"main": "no main checkout"})))
    assert result.status == "error" and "no main checkout" in result.summary


def test_console_tactile_frames_counts_what_the_consoles_own_stream_stores():
    frames = iter([120, 220])
    session = SimpleNamespace(tactile_stats=lambda: SimpleNamespace(frames_ok=next(frames)))
    waited = []
    assert compare.console_tactile_frames(SimpleNamespace(session=session), waited.append) == 100
    assert waited == [compare.CONSOLE_TACTILE_WINDOW_S]


def test_console_tactile_frames_is_none_without_a_tactile_stream():
    no_tactile = SimpleNamespace(session=SimpleNamespace(tactile_stats=lambda: None))
    assert compare.console_tactile_frames(no_tactile, lambda s: None) is None
    assert compare.console_tactile_frames(SimpleNamespace(session=None), lambda s: None) is None

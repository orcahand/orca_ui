"""Hardware tests: the checks that judge a hands-on step from what the session
recorded (operation log, operations, readings, script logs) and the software
run. Synthetic recordings only; no console, no hand."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from orca_ui.hardware_tests.checks import evidence, software

STAGES = {"ring": ["ring_abd", "ring_mcp", "ring_pip"], "pinky": ["pinky_abd", "pinky_mcp", "pinky_pip"]}
HOLDS = {"ring_abd": {200.0}, "ring_mcp": {140.0}, "ring_pip": {100.0},
         "pinky_abd": {200.0}, "pinky_mcp": {140.0, 120.0}, "pinky_pip": {100.0}}


def _line(phase, stage, cells, mismatch=""):
    body = ", ".join(f"{j} {a:g}→{'none' if h is None else format(h, 'g')}" for j, a, h in cells)
    label = phase + (f", {stage}" if stage else "")
    return f"current limits ({label}), asked→held mA:{mismatch} {body}"


def _judge(*lines):
    entries = [evidence.parse_limit_line(line) for line in lines]
    return evidence.judge_limits(entries, tension_ma=300.0, stages=STAGES,
                                 allowed=lambda j: HOLDS.get(j, set()), tolerance=7.0)


def test_read_back_lines_parse_and_a_correct_run_has_no_problems():
    good = _line("range check", "ring", [("wrist", 100, None), ("ring_abd", 200, 200), ("ring_mcp", 140, 140),
                                          ("ring_pip", 100, 100), ("pinky_abd", 300, 300), ("pinky_mcp", 300, 300)])
    parsed = evidence.parse_limit_line(good)
    assert parsed["phase"] == "range check" and parsed["stage"] == "ring"
    assert parsed["limits"]["wrist"] == (100.0, None) and parsed["limits"]["ring_mcp"] == (140.0, 140.0)
    pull = _line("pull", None, [("ring_mcp", 300, 300)])
    assert _judge(good, pull) == []
    assert evidence.parse_limit_line("joint calibrated: ring_mcp (ratio 0.0188)") is None


def test_read_back_problems_name_the_joint_and_what_was_wrong():
    problems = _judge(
        _line("range check", "ring", [("ring_mcp", 300, 300), ("pinky_mcp", 140, 140)]),
        _line("pull", None, [("ring_abd", 300, 0)], mismatch=" MISMATCH on ring_abd;"),
    )
    assert any("moved ring_mcp at 300" in p for p in problems)
    assert any("frozen pinky_mcp at 140" in p for p in problems)
    assert any("ring_abd asked 300 mA, holds 0 mA" in p for p in problems)


def _ctx(tmp_path, step="A4c", lines=(), operations=(), visits=(), events=None, **extra):
    step_dir = tmp_path / step
    step_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"topics": {"operation.state": {"data": {"run_id": "gt-1", "extra": {
        "step": "pose", "round": r, "stage_index": s}}}}} for r, s in visits]
    with open(step_dir / "readings.jsonl", "w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    step_events = [{"type": "operation_log", "step": step, "line": line} for line in lines]
    return SimpleNamespace(
        step=SimpleNamespace(id=step), out_dir=step_dir, hand=SimpleNamespace(hardware_version=210),
        step_events=lambda sid: step_events, step_operations=lambda sid: list(operations),
        session_events=lambda: events if events is not None else step_events,
        step_dir=lambda sid: step_dir, **extra)


def test_in_run_controls_pass_when_each_one_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "read_back", lambda ctx, step, runs: None)
    run = {"kind": "guided_tension", "run_id": "gt-1", "state": "done", "extra": {"scoring": "fraction"}}
    ctx = _ctx(tmp_path, lines=["ring_mcp: tested again, its earlier pass dropped", "hold mcp set to 120 mA"],
               operations=[run], visits=[(1, 0), (1, 1), (1, 0), (1, 1), (1, 3)])
    result = evidence.guided_tension_controls(ctx)
    assert result.status == "pass", result.summary
    assert "Not verified" in result.summary

    bare = _ctx(tmp_path / "bare", operations=[run], visits=[(1, 0), (1, 1), (2, 0), (2, 1)])
    result = evidence.guided_tension_controls(bare)
    assert result.status == "fail"
    assert "no Back or jump" in result.summary and "test again" in result.summary
    assert evidence.guided_tension_controls(_ctx(tmp_path / "none")).status == "fail"


def test_every_latch_must_clear_and_no_latch_is_nothing_to_verify(tmp_path):
    latched = {"type": "operation_log", "step": "A4a", "t": "2026-01-01T10:41:29",
               "line": "motor 7 (ring_mcp) has latched overload and is not holding — reboot it to continue"}
    cleared = {"type": "operation_log", "step": "A4a", "t": "2026-01-01T10:41:33",
               "line": "motor 7 cleared and holding again"}
    auto = {"type": "log_record", "step": "C4", "t": "2026-01-01T12:04:59",
            "message": "Motor 15 overload detected (error=0x20), rebooting..."}
    ok = evidence.latched_motor_recovered(_ctx(tmp_path, step="A14", events=[latched, cleared, auto]))
    assert ok.status == "pass" and "cleared 10:41:33" in ok.summary
    assert evidence.latched_motor_recovered(_ctx(tmp_path, step="A14", events=[latched])).status == "fail"
    none = evidence.latched_motor_recovered(_ctx(tmp_path, step="A14", events=[auto]))
    assert none.status == "skipped" and "motor 15" in none.summary


def test_simple_tensioning_needs_a_restart_and_no_error(tmp_path):
    stopped = {"kind": "tension", "state": "done", "result": None}
    released = {"kind": "tension", "state": "done", "result": {"released": True}}
    assert evidence.simple_tension_jumps(_ctx(tmp_path, step="A15", operations=[stopped, released])).status == "pass"
    assert evidence.simple_tension_jumps(_ctx(tmp_path, step="A15", operations=[released])).status == "fail"
    broken = {"kind": "tension", "state": "error", "error": "bus lost"}
    assert evidence.simple_tension_jumps(_ctx(tmp_path, step="A15", operations=[stopped, broken])).status == "fail"


def test_the_board_menu_must_name_the_consoles_board(tmp_path):
    def ctx(boards):
        return _ctx(tmp_path, step="A16", service=SimpleNamespace(boards=lambda: boards))

    held = {"held_by_console": True, "serial": "ser-0000", "board_id": "0123456789ABCDEF"}
    assert evidence.board_identity_listed(ctx({"available": True, "boards": [held]})).status == "pass"
    assert evidence.board_identity_listed(
        ctx({"available": True, "boards": [{**held, "board_id": None}]})).status == "fail"
    assert evidence.board_identity_listed(ctx({"available": False, "boards": []})).status == "skipped"


def test_script_logs_show_a_full_calibration_and_a_slack_scored_run(tmp_path):
    joints = ["ring_abd", "ring_mcp"]
    (tmp_path / "calibrate.log").write_text(
        "  ring_abd calibrated (ratio 0.0143)\n  ring_mcp calibrated (ratio 0.0188)\n"
        "  ring_mcp motor travel 131.6 deg vs 128.0 deg baseline (+3%, accept 96.0-160.0) [ok]\n")
    (tmp_path / "guided_tension.log").write_text(
        "The ring motors hold this pose at 100-200 mA; the other fingers are frozen at 300 mA.\n"
        "  motor  7  ####  (120 of 128 deg, tolerance 5°, ends +2/-2)\nFinished below 100%.\n")
    judged = evidence.judge_script_logs(tmp_path, finger_joints=joints, v21=True, tension_ma=300.0)
    assert judged["problems"] == []

    (tmp_path / "guided_tension.log").write_text("Traceback (most recent call last):\n")
    (tmp_path / "calibrate.log").unlink()
    problems = evidence.judge_script_logs(tmp_path, finger_joints=joints, v21=True, tension_ma=300.0)["problems"]
    assert any("calibrate.log is missing" in p for p in problems)
    assert any("Traceback" in p for p in problems)


def test_the_software_run_links_this_orca_ui_and_judges_exit_codes(tmp_path, monkeypatch):
    code = tmp_path / "code"
    for name in ("orca_core", "orca_ui", "orca_teleop"):
        (code / name).mkdir(parents=True)
    ui = tmp_path / "elsewhere" / "orca_ui-checkout"
    ui.mkdir(parents=True)
    links = software.repos_root(tmp_path / "links", code / "orca_core", ui)
    assert (links / "orca_ui").resolve() == ui.resolve()
    assert (links / "orca_teleop").resolve() == (code / "orca_teleop").resolve()
    assert software.tally("x\n538 passed, 14 warnings in 46.7s\n") == "538 passed, 14 warnings"

    monkeypatch.setattr(software, "branch_core", lambda: (code / "orca_core", None))
    ctx = _ctx(tmp_path, step="S1", stop_event=threading.Event(), log=lambda line: None,
               progress=lambda f, d="": None, check_stop=lambda: None)
    monkeypatch.setattr(software, "commands", lambda core, ui, links, py: [
        ("one", tmp_path, ["sh", "-c", "echo '3 passed in 0.1s'"], {}),
        ("two", tmp_path, ["sh", "-c", "exit 1"], {})])
    result = software.software_suites(ctx)
    assert result.status == "fail" and "two" in result.summary
    assert (ctx.out_dir / "one.log").read_text().strip() == "3 passed in 0.1s"

    monkeypatch.setattr(software, "branch_core", lambda: (None, "the console runs a released orca_core"))
    assert software.software_suites(ctx).status == "skipped"


def test_guided_tensioning_scores_against_one_complete_table(tmp_path, monkeypatch):
    from orca_ui.hand.operations import guided_tension

    joints = ["ring_abd", "ring_mcp"]
    config = SimpleNamespace(joint_ids=["wrist", *joints], joint_to_motor_map={"wrist": 1, "ring_abd": 6, "ring_mcp": 7},
                             expected_motor_travel_deg=lambda j: None)
    label = "the reference hand ser-0000 (manual_reference)"
    monkeypatch.setattr(guided_tension, "motor_family", lambda service: "dynamixel")
    monkeypatch.setattr(guided_tension, "active_travel_baseline", lambda c, f: (
        {"label": label, "source": "reference"}, {"ring_abd": 44.0, "ring_mcp": 128.0}))
    service = SimpleNamespace(supervisor=SimpleNamespace(config=config), session=None)
    logged = [{"type": "operation_log", "line": f"scoring against {label}"}]
    ok = evidence.guided_tension_baseline(_ctx(tmp_path, step="A13", service=service, events=logged))
    assert ok.status == "pass", ok.summary

    other = logged + [{"type": "operation_log", "line": "scoring against baseline GT_01 (manual)"}]
    assert evidence.guided_tension_baseline(_ctx(tmp_path, step="A13", service=service, events=other)).status == "fail"
    monkeypatch.setattr(guided_tension, "active_travel_baseline", lambda c, f: (
        {"label": label, "source": "reference"}, {"ring_abd": 44.0}))
    short = evidence.guided_tension_baseline(_ctx(tmp_path, step="A13", service=service, events=logged))
    assert short.status == "fail" and "ring_mcp" in short.summary

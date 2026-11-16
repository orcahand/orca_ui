"""The release plan's checks on the mock console: each runs to a verdict, puts
the hand's files and settings back, and leaves torque off. Plus the safety
helpers on their own (file restore on a failure, torque read-back)."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orca_ui.hardware_tests import catalog as cat
from orca_ui.hardware_tests.checks import release
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

H = "/api/hardware-tests"
PLAN = "release-0.14"


def _wait_for(predicate, timeout=60.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client(tmp_path):
    settings = UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False,
                          hardware_tests=True, bench_dir=str(tmp_path / "bench"))
    with TestClient(create_app(settings)) as test_client:
        assert _wait_for(lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _run(client, step_ids):
    assert client.post(H + "/auto/run", json={"step_ids": step_ids, "force": True}).status_code == 200
    done = _wait_for(lambda: (lambda s: s if s["auto"]["state"] == "idle" else None)(
        client.get(H + "/state").json()["session"]), timeout=120.0)
    return {s["id"]: s["result"] for f in done["features"] for s in f["steps"]}


def test_the_release_plan_is_offered_first_and_people_only_get_hands_on_steps():
    catalog = cat.load_catalog()
    assert next(iter(catalog.plans)) == PLAN
    features = catalog.plan_features(PLAN)
    assert features[0].id == "r14-hands-on"
    hands_on = [s for f in features for s in f.steps if cat.is_hands_on(s)]
    assert hands_on and all(s.id.startswith("H") for s in hands_on)


def test_release_checks_run_on_the_mock_hand_and_put_everything_back(client):
    client.post(H + "/session", json={"plan_id": PLAN, "hand_label": "mock"})
    nickname = client.get("/api/hand/info").json()["hand"]["nickname"]
    before = client.get("/api/status").json()
    steps = ["R1a", "R1b", "R2a", "R4b", "R7c", "R9a", "R11a", "R12a", "R13a", "R17a", "R18a", "R19a", "R6c", "R6d"]
    results = _run(client, steps)
    for sid in steps:
        result = results[sid]
        assert result["status"] in ("pass", "skipped"), (sid, result["check"]["summary"], result["check"]["metrics"])
    info = client.get("/api/hand/info").json()
    assert info["hand"]["nickname"] == nickname
    status = client.get("/api/status").json()
    assert status["torque_enabled"] is False and status["hardware_version_override"] is None
    assert status["state"] == "connected"
    assert before["hardware_version"] == status["hardware_version"]


def test_the_other_release_checks_reach_a_verdict_on_the_mock_hand(client):
    client.post(H + "/session", json={"plan_id": PLAN, "hand_label": "mock"})
    steps = ["R1c", "R3a", "R3b", "R4a", "R5a", "R7a", "R7b", "R10a", "R15a", "R16a", "R20a", "R6g"]
    results = _run(client, steps)
    verdicts = {sid: (results[sid]["status"], results[sid]["check"]["summary"]) for sid in steps}
    assert not [(k, v) for k, v in verdicts.items() if v[0] not in ("pass", "skipped", "observed")]
    assert client.get("/api/status").json()["torque_enabled"] is False


def test_files_are_put_back_even_when_the_check_fails(tmp_path, monkeypatch):
    folder = tmp_path / "hand"
    folder.mkdir()
    (folder / "calibration.yaml").write_text("mine\n")
    calls = []
    service = SimpleNamespace(session=None, reconnect=lambda: calls.append("reconnect"),
                              status=lambda: {"state": "connected"}, session_ready=True)
    ctx = SimpleNamespace(out_dir=tmp_path / "out", service=service, log=lambda line: None,
                          check_stop=lambda: None, wait=lambda s: None)
    monkeypatch.setattr(release, "_hand_dir", lambda c: folder)
    monkeypatch.setattr(release, "calibration_file", lambda c: folder / "calibration.yaml")
    with pytest.raises(RuntimeError):
        with release.hand_files_restored(ctx, ("calibration.yaml", "joint_ranges.yaml")):
            (folder / "calibration.yaml").write_text("garbage\n")
            (folder / "joint_ranges.yaml").write_text("joint_roms: {}\n")
            raise RuntimeError("the check failed half way")
    assert (folder / "calibration.yaml").read_text() == "mine\n"
    assert not (folder / "joint_ranges.yaml").exists()
    assert calls == ["reconnect"]


def test_torque_read_back_names_motors_still_on_or_silent():
    metrics, problems = release._torque_metrics({1: False, 2: True, 3: None})
    assert metrics[0].ok is False
    assert problems == ["torque still on for motor(s) 2", "no torque read-back from motor(s) 3"]
    assert release._torque_metrics({1: False, 2: False})[1] == []


def test_gains_are_only_asked_of_a_hand_with_a_joint_feedback_loop():
    assert release.has_feedback_loop({"capabilities": {"feedback_loop": True}})
    assert not release.has_feedback_loop({"capabilities": {"feedback_loop": False}})
    assert not release.has_feedback_loop({})


def test_the_edited_max_current_is_valid_for_the_family_and_differs_from_the_one_in_force():
    feetech = SimpleNamespace(calibration_current=500, wrist_calibration_current=500,
                              calibration_max_current=None, max_current=1000)
    assert release.edited_max_current(feetech) == 990
    assert release.edited_max_current(feetech, wanted=200) == 990  # below the calibration current
    tight = SimpleNamespace(calibration_current=500, wrist_calibration_current=500,
                            calibration_max_current=None, max_current=505)
    chosen = release.edited_max_current(tight)
    assert chosen > 500 and chosen != 505


def test_the_store_snapshot_ignores_the_consoles_own_reconnect_but_not_a_real_write(tmp_path):
    hand = tmp_path / "ser-1"
    hand.mkdir()
    (hand / "hand.yaml").write_text("id: ser-1\nnickname: a\nlast_seen: '1'\n")
    (hand / "setup.yaml.lock").write_text("")
    before = release.store_snapshot(tmp_path)
    (hand / "hand.yaml").write_text("id: ser-1\nnickname: a\nlast_seen: '2'\n")
    (hand / "setup.yaml.lock").touch()
    assert release.snapshot_changes(before, release.store_snapshot(tmp_path)) == []
    (hand / "calibration.yaml").write_text("sequence: 1\n")
    (hand / "hand.yaml").write_text("id: ser-1\nnickname: b\nlast_seen: '3'\n")
    assert release.snapshot_changes(before, release.store_snapshot(tmp_path)) == \
        ["ser-1/calibration.yaml", "ser-1/hand.yaml"]


def test_the_sweep_is_judged_on_what_it_commands_and_its_mean_not_its_peaks():
    capped = {"sweep_current_ma": 100.0, "hold_current_ma": 100.0, "pose_current_ma": 100.0, "speed_deg_s": 30}
    readings = [{"mean_ma": 14.9, "peak_ma": 195.0}, {"mean_ma": -15.2, "peak_ma": 208.0}]
    metrics = release.sweep_current_metrics(capped, readings, 100, 15.0)
    assert [m.ok for m in metrics] == [True, True, None] and metrics[2].value == 208.0
    over = release.sweep_current_metrics({**capped, "sweep_current_ma": 150.0}, readings, 100, 15.0)
    assert over[0].ok is False
    assert release.sweep_current_metrics(capped, [{"mean_ma": 140.0}], 100, 15.0)[1].ok is False


def test_holding_stops_on_a_hot_motor_and_names_the_hottest_with_its_tracking_error():
    start = {10: 32.0, 12: 32.0, 1: 29.0}
    assert release.holding_abort(start, {10: 40.0, 12: 33.0, 1: 29.0}, 15.0, 60.0) is None
    assert "warmed by 16" in release.holding_abort(start, {10: 48.0, 12: 33.0, 1: 29.0}, 15.0, 60.0)
    assert "reached 60" in release.holding_abort({10: 50.0}, {10: 60.0}, 15.0, 60.0)
    table = release.holding_table(start, {10: 54.0, 12: 56.0, 1: 29.0}, {10: [338.0, 368.0], 12: [455.0]},
                                  {10: "middle_mcp", 12: "pinky_mcp", 1: "wrist"}, {"pinky_mcp": -49.7})
    assert [r["motor"] for r in table] == [12, 10, 1]
    assert table[0]["error_deg"] == -49.7 and table[1]["error_deg"] is None and table[1]["mean_ma"] == 353.0


def test_the_board_step_needs_the_store_tool_and_reads_calibrates_own_verdict(tmp_path, monkeypatch):
    plain, tooled = tmp_path / "plain", tmp_path / "tooled"
    (plain / ".git").mkdir(parents=True)
    (tooled / release.FIRMWARE_TOOL).parent.mkdir(parents=True)
    (tooled / release.FIRMWARE_TOOL).write_text("")
    ctx = SimpleNamespace(step=SimpleNamespace(params={"firmware_repo": str(plain)}), sides=SimpleNamespace())
    monkeypatch.setattr(release.Path, "home", lambda: tmp_path / "nobody")
    assert release.firmware_repo(ctx) is None
    ctx.step.params["firmware_repo"] = str(tooled)
    assert release.firmware_repo(ctx) == tooled.resolve()
    kept = "WARNING board ...\nCalibration kept on this computer only: no orca_firmware checkout on this computer.\n"
    assert release.board_write_outcome(0, kept) == ("not_written", "no orca_firmware checkout on this computer")
    assert release.board_write_outcome(0, "Calibration also written to the hand's own board (seq 3).")[0] == "wrote"
    assert release.board_write_outcome(0, "the board answered")[0] == "failed"
    assert release.board_write_outcome(1, kept)[0] == "failed"

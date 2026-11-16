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


def test_the_store_snapshot_sees_any_write_even_a_last_seen_stamp_or_a_lock(tmp_path):
    hand = tmp_path / "ser-1"
    hand.mkdir()
    (hand / "hand.yaml").write_text("id: ser-1\nlast_seen: '1'\n")
    (hand / "setup.yaml.lock").write_text("")
    before = release.store_snapshot(tmp_path)
    assert release.snapshot_changes(before, release.store_snapshot(tmp_path)) == []
    (hand / "hand.yaml").write_text("id: ser-1\nlast_seen: '22'\n")
    (hand / "setup.yaml.lock").write_text("x")
    assert release.snapshot_changes(before, release.store_snapshot(tmp_path)) == \
        ["ser-1/hand.yaml", "ser-1/setup.yaml.lock"]


def test_the_custom_home_run_is_compared_only_while_the_console_has_let_go(tmp_path, monkeypatch):
    real = tmp_path / "real-hands"
    (real / "ser-1").mkdir(parents=True)
    (real / "ser-1" / "hand.yaml").write_text("id: ser-1\n")
    released = []

    class Sides:
        @staticmethod
        def available(side):
            return None

        @staticmethod
        @release.contextlib.contextmanager
        def hand_released():
            released.append("in")
            yield
            # The console takes the hand back and stamps its folder: outside the comparison.
            (real / "ser-1" / "hand.yaml").write_text("id: ser-1\nlast_seen: now\n")

    def connect(ctx, folder, **args):
        assert released == ["in"]
        return {"ok": True, "data": {"hand_dir": str(ctx.out_dir / "connect" / "orca_home" / "hands" / "ser-1")}}

    monkeypatch.setattr(release, "hands_root", lambda: real)
    monkeypatch.setattr(release, "_mock", lambda ctx: False)
    monkeypatch.setattr(release, "_connect_only", connect)
    ctx = SimpleNamespace(out_dir=tmp_path / "out", sides=Sides(), step=SimpleNamespace(params={}))
    result = release.orca_home_elsewhere(ctx)
    assert result.status == "pass", result.summary

    def leaky(ctx, folder, **args):
        (real / "ser-1" / "hand.yaml").write_text("id: ser-1\nlast_seen: leaked by the side run\n")
        return connect(ctx, folder)

    released.clear()
    monkeypatch.setattr(release, "_connect_only", leaky)
    result = release.orca_home_elsewhere(ctx)
    assert result.status == "fail" and result.details["changed_in_real_store"] == ["ser-1/hand.yaml"]


# The 100 mA run on the Feetech bench hand (2026-11-16): flex barely drew, extend held about twice the limit,
# and index_mcp stayed at 11.95 deg throughout.
_STUCK = 11.95
_FLEX = {"joint": "index_mcp", "sense": "flex", "mean_ma": 14.92, "start_deg": _STUCK, "end_deg": _STUCK,
         "samples": [[_STUCK, -195.0], [_STUCK, -195.0]] + [[_STUCK, -6.5]] * 42}
_EXTEND = {"joint": "index_mcp", "sense": "extend", "mean_ma": 158.44, "start_deg": _STUCK, "end_deg": _STUCK,
           "samples": [[_STUCK, -6.5], [_STUCK, -6.5], [_STUCK, 0.0], [_STUCK, 97.5]]
           + [[_STUCK, ma] for ma in (-201.5, -208.0, -208.0, -201.5, -201.5, -201.5,
                                      -195.0, -208.0, -208.0, -201.5, -195.0, -195.0)]}
_CAPPED = {"sweep_current_ma": 100.0, "hold_current_ma": 100.0, "pose_current_ma": 100.0, "speed_deg_s": 30}


def test_the_real_100_ma_run_fails_on_held_current_and_on_a_joint_that_never_moved():
    by = {m.name: m for m in release.sweep_current_metrics(_CAPPED, [_FLEX, _EXTEND], 100)}
    assert by["sweep's highest commanded current"].ok is True
    held = by["drive current held above the limit"]
    assert held.ok is False and "extend: 12/16" in held.value and "flex" not in held.value
    assert by["sweep's highest drive current reading"].value == 208.0
    assert by["did not move at this current"].ok is False


def test_a_sweep_within_its_limit_that_moved_passes_and_a_commanded_overshoot_fails():
    moving = {"joint": "index_mcp", "sense": "flex", "mean_ma": 60.0,
              "samples": [[float(a), 60.0] for a in range(0, 90, 5)] + [[90.0, 160.0]]}
    metrics = release.sweep_current_metrics(_CAPPED, [moving], 100)
    assert [m.ok for m in metrics] == [True, True, None, True]
    assert release.sweep_current_metrics({**_CAPPED, "sweep_current_ma": 150.0}, [moving], 100)[0].ok is False


def test_the_goal_current_read_back_flags_a_motor_above_the_limit():
    def service(read):
        client = SimpleNamespace(read_goal_currents=read)
        return SimpleNamespace(session=SimpleNamespace(hand=SimpleNamespace(motor_client=client)))
    assert release.goal_current_metric(service(lambda: {1: 97.5, 2: 97.5}), 100).ok is True
    above = release.goal_current_metric(service(lambda: {1: 97.5, 2: 899.6}), 100)
    assert above.ok is False and "[2]" in above.value
    assert release.goal_current_metric(SimpleNamespace(session=None), 100).ok is None


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


@pytest.mark.parametrize("reason, outcome", [
    ("no orca_firmware checkout at /x/orca_firmware", "not_written"),
    ("the orca_firmware checkout at /x/orca_firmware has no tools/bench/cal_store.py", "not_written"),
    ("this hand has no board to keep a calibration on", "not_written"),
    ("the board on /dev/cu.usbmodem101 did not answer (timeout)", "failed"),
    ("the firmware tool would not run (exit 2)", "failed"),
    ("the board does not serve the calibration just written", "failed"),
    ("the board was not written (OSError: boom)", "failed"),
])
def test_only_nothing_to_write_with_or_to_is_a_skip_and_every_failed_write_fails(reason, outcome):
    got = release.board_write_outcome(0, f"Calibration kept on this computer only: {reason}.\n")
    assert got == (outcome, reason)

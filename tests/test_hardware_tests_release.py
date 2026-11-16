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

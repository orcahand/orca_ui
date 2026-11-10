"""The Tests tab's REST contract over the mock hand, and the console checks
that are safe to run on it: the slack test and sweep refusing while the joint
loop runs, and a motor reboot with torque on."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hardware_tests import session as hw_session
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

H = "/api/hardware-tests"


def _wait_for(predicate, timeout=10.0, interval=0.05):
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


def test_disabled_tab_answers_state_and_refuses_writes(client, monkeypatch):
    monkeypatch.setattr(hw_session, "tab_enabled", lambda settings: False)
    assert client.get(H + "/state").json() == {"enabled": False, "plans": [], "session": None,
                                               "default_label": None}
    assert client.post(H + "/session", json={"plan_id": "merge-0.13"}).status_code == 404


def test_session_contract_and_safe_console_checks(client):
    assert client.get("/api/hand/info").json()["hardware_tests"] is True
    state = client.get(H + "/state").json()
    assert state["enabled"] and any(p["id"] == "merge-0.13" for p in state["plans"])

    session = client.post(H + "/session", json={"plan_id": "merge-0.13", "hand_label": "ser-0000"}).json()
    for key in ("id", "plan_id", "plan_title", "started_at", "finished_at", "results_dir", "index_file",
                "hand", "sides", "auto", "open_step", "features"):
        assert key in session
    assert set(session["sides"]) == {"main", "branch"}
    step = session["features"][0]["steps"][0]
    for key in ("id", "kind", "instructions", "pass_rule", "applies_to", "panels", "action", "check",
                "applicable", "not_applicable_reason", "result"):
        assert key in step

    assert client.post(H + "/steps/A1/open").json()["open_step"] == "A1"
    assert client.post(H + "/steps/A1/screenshot", content=b"not a png").status_code == 415
    shot = client.post(H + "/steps/A1/screenshot", content=b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    assert shot.json()["file"].endswith("A1/screenshots/1.png")
    assert client.post(H + "/steps/A1/close").json()["open_step"] is None

    assert client.post(H + "/auto/run", json={"step_ids": ["A2"]}).status_code == 409
    assert client.post(H + "/auto/run", json={"step_ids": ["A2", "A10"], "force": True}).status_code == 200
    done = _wait_for(lambda: (lambda s: s if s["auto"]["state"] == "idle" else None)(
        client.get(H + "/state").json()["session"]), timeout=30.0)
    steps = {s["id"]: s for f in done["features"] for s in f["steps"]}
    assert steps["A2"]["result"]["status"] == "pass", steps["A2"]["result"]["check"]["summary"]
    assert steps["A10"]["result"]["status"] == "pass", steps["A10"]["result"]["check"]["summary"]
    # The reboot check put the hand back as it found it: limp.
    assert client.get("/api/status").json()["torque_enabled"] is False
    assert client.post(H + "/session/end").json() == {}

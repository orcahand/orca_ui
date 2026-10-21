"""Tension probe: the dataset the console saves after a run, and the lease it
must release when e-stopped mid-probe (a motor is pulling on a tendon then)."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.03}


def _wait_for(predicate, timeout=20.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client():
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True, open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"] or {}


def test_a_probe_run_saves_a_named_dataset_with_every_pass(client):
    before = client.get("/api/probes").json()
    assert before["probes"] == {}

    response = client.post("/api/operation/tension_probe/start",
                           json={"params": {**FAST, "joints": ["index_pip", "middle_mcp", "middle_pip"],
                                            "methods": ["takeup", "breakaway"], "repeats": 2,
                                            "ignore_calibration": True, "pose": "mid"}})
    assert response.status_code == 200, response.text
    # A check first waits, torque off, for the operator to pose the hand clear of its stops.
    assert _wait_for(lambda: _operation(client).get("state") == "awaiting_input")
    assert _operation(client)["extra"]["step"] == "pose"
    assert client.post("/api/operation/input", json={"value": "Continue"}).status_code == 200
    assert _wait_for(lambda: _operation(client).get("state") == "done")
    snapshot = _operation(client)
    name = snapshot["result"]["saved"]
    # Named by what and when, so the file reads on its own.
    assert name.startswith("check_20") and snapshot["result"] == {"saved": name, "results": 24}
    extra = snapshot["extra"]
    assert extra["step"] == "done" and extra["saved"] == name
    assert extra["repeats"] == 2 and extra["total"] == 24 and extra["done"] == 24
    # A tension check holds where it stands whatever pose was asked for.
    assert extra["check"] is True and extra["pose"] == "hold"

    probes = client.get("/api/probes").json()
    saved = probes["probes"][name]
    assert saved["methods"] == ["takeup", "breakaway"] and saved["repeats"] == 2 and saved["check"] is True
    by = {(r["joint"], r["direction"], r["method"], r["run"]): r for r in saved["results"]}
    assert by[("index_pip", 1, "takeup", 1)]["free_deg"] is not None
    assert by[("index_pip", -1, "breakaway", 2)]["curve"]
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
    assert client.post("/api/operation/tension_probe/start",
                       json={"params": {"methods": ["nope"]}}).status_code == 422
    assert client.post("/api/operation/tension_probe/start",
                       json={"params": {"repeats": 11}}).status_code == 422


def test_estop_mid_probe_releases_the_lease(client):
    client.post("/api/operation/tension_probe/start",
                json={"params": {"step_duration_s": 0.5}})
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "maintenance")
    assert client.post("/api/estop").status_code == 200
    assert _wait_for(lambda: _operation(client).get("state") == "error")
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
    assert client.get("/api/probes").json()["probes"] == {}


def test_probe_refuses_the_wrist_and_currents_above_the_hands_ceiling(client):
    assert client.post("/api/operation/tension_probe/start",
                       json={"params": {"joints": ["wrist"]}}).status_code == 422
    ceiling = float(client.app.state.service.supervisor.config.max_current)
    response = client.post("/api/operation/tension_probe/start",
                           json={"params": {"hold_current_ma": ceiling + 50}})
    assert response.status_code == 422, response.text
    assert client.get("/api/status").json()["state"] == "connected"   # nothing was scheduled


def test_a_check_opens_the_ratchet_and_runs_again_inside_each_round(client):
    """The dialog's "Continue to tensioning" opens guided tensioning on the
    check's results straight at the ratchet; every later round offers the
    check between the range check and the ratchet and publishes it under
    ``extra.check`` with the hand limp for the pose prompt first."""
    client.post("/api/operation/tension_probe/start",
                json={"params": {**FAST, "joints": ["index_pip"], "ignore_calibration": True, "note": "before clicks"}})
    assert _wait_for(lambda: _operation(client).get("state") == "awaiting_input")
    client.post("/api/operation/input", json={"value": "Continue"})
    assert _wait_for(lambda: _operation(client).get("state") == "done")
    first = _operation(client)["result"]["saved"]
    assert client.get("/api/probes").json()["probes"][first]["note"] == "before clicks"
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")

    response = client.post("/api/operation/guided_tension/start",
                           json={"params": {**FAST, "any_hardware": True, "check_from": first,
                                            "start_at": "tension"}})
    assert response.status_code == 200, response.text
    prompt = _wait_for(lambda: (lambda o: o if o.get("state") == "awaiting_input" else None)(_operation(client)))
    assert prompt["extra"]["step"] == "tension" and prompt["extra"]["check"]["saved"] == first
    assert prompt["extra"]["check"]["results"][0]["joint"] == "index_pip"
    client.post("/api/operation/input", json={"value": "Done"})

    def at(step):
        return lambda: (lambda o: o if o.get("state") == "awaiting_input" and (o.get("extra") or {}).get("step") == step
                        else None)(_operation(client))

    assert _wait_for(at("pose"))
    client.post("/api/operation/input", json={"value": "goto:score"})
    prompt = _wait_for(at("score"))
    assert prompt["awaiting"]["options"][0] == "Check & tension"
    client.post("/api/operation/input", json={"value": "Check & tension"})
    prompt = _wait_for(at("check_pose"))
    assert prompt["awaiting"]["options"] == ["Continue", "Skip check"]
    client.post("/api/operation/input", json={"value": "Continue"})
    prompt = _wait_for(at("tension"))
    check = prompt["extra"]["check"]
    assert check["step"] == "done" and check["round"] == 2 and check["saved"] != first
    assert check["total"] == len(check["results"]) == check["done"] > 0
    assert client.get("/api/probes").json()["probes"][check["saved"]]["note"] == "guided tensioning round 2"
    assert client.post("/api/operation/stop").status_code == 200
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
    assert client.post("/api/operation/guided_tension/start",
                       json={"params": {"any_hardware": True, "check_from": "nope"}}).status_code == 422

"""Slack test and tension sweep: a half-turn-free spool blocks calibration until
a passing test; a sweep is saved as a named dataset and scored against the
reference. Both release the lease when e-stopped."""

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
        assert _wait_for(lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"] or {}


def _done(client):
    assert _wait_for(lambda: _operation(client).get("state") in ("done", "error"))
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
    return _operation(client)


def test_a_half_turn_free_spool_blocks_calibration_until_a_passing_test(client):
    response = client.post("/api/operation/slack_test/start",
                           json={"params": {**FAST, "unspool": ["ring_mcp"]}})
    assert response.status_code == 200, response.text
    snapshot = _done(client)
    assert snapshot["state"] == "done" and snapshot["result"]["blocked"] is True
    assert snapshot["result"]["slack"]["ring_mcp"] == "unspool"
    extra = snapshot["extra"]
    assert extra["step"] == "done" and extra["results"]["ring_mcp"]["plus_capped"]
    info = client.get("/api/hand/info").json()["slack_test"]
    assert info["blocked"] and "ring_mcp" in info["block"]

    blocked = client.post("/api/operation/calibrate/start", json={"params": FAST})
    assert blocked.status_code == 409 and "ring_mcp" in blocked.json()["detail"]
    assert client.post("/api/operation/calibrate/start",
                       json={"params": {**FAST, "manual": True}}).status_code == 409

    assert client.post("/api/operation/slack_test/start", json={"params": FAST}).status_code == 200
    snapshot = _done(client)
    assert snapshot["result"]["blocked"] is False
    assert set(snapshot["result"]["slack"].values()) <= {"taut", "slack"}
    assert client.get("/api/hand/info").json()["slack_test"]["block"] is None
    assert len(client.get("/api/slack_tests").json()["tests"]) == 2
    assert client.post("/api/operation/calibrate/start",
                       json={"params": {**FAST, "joints": ["index_pip"]}}).status_code == 200
    _done(client)
    assert client.post("/api/operation/slack_test/start",
                       json={"params": {"current_ma": 500}}).status_code == 422


def test_a_sweep_is_saved_and_scored_against_the_reference(client):
    before = client.get("/api/sweeps").json()
    assert before["sweeps"] == {} and before["supported"]

    response = client.post("/api/operation/tension_sweep/start",
                           json={"params": {**FAST, "joints": ["index_pip", "middle_mcp"], "repeats": 2}})
    assert response.status_code == 200, response.text
    snapshot = _done(client)
    name = snapshot["result"]["saved"]
    assert name.startswith("sweep_20") and snapshot["result"] == {"saved": name, "results": 8}
    extra = snapshot["extra"]
    assert extra["step"] == "done" and extra["repeats"] == 2 and extra["total"] == 8
    assert extra["reference"] is None and extra["verdict"]["joints"]["index_pip"]["status"] == "none"
    assert isinstance(extra["results"][0]["samples"], int)

    saved = client.get(f"/api/sweeps/{name}").json()
    by = {(r["joint"], r["direction"], r["run"]): r for r in saved["results"]}
    assert by[("index_pip", 1, 2)]["samples"] and by[("index_pip", 1, 2)]["mean_ma"] > 50
    assert client.post("/api/sweeps/reference", json={"name": name}).status_code == 200
    info = client.get("/api/hand/info").json()["tension_sweep"]
    assert {k: info[k] for k in ("reference", "latest", "latest_at")} == {
        "reference": name, "latest": name, "latest_at": saved["recorded_at"]}
    # The newest sweep scored against the reference rides along: the reference against itself is ok.
    assert info["verdict"]["index_pip"]["status"] == "ok"

    # A loose index_pip reads as under-tensioned against the reference; middle_mcp is fine.
    response = client.post("/api/operation/tension_sweep/start",
                           json={"params": {**FAST, "joints": ["index_pip", "middle_mcp"],
                                            "load_scale": {"index_pip": 0.5}}})
    assert response.status_code == 200, response.text
    extra = _done(client)["extra"]
    assert extra["reference"] == name and extra["saved"] != name
    joints = extra["verdict"]["joints"]
    # Scored as curves: the loose tendon's friction runs below the reference's along the whole travel.
    assert joints["index_pip"]["status"] == "low" and joints["index_pip"]["share"] < 0.7
    assert joints["index_pip"]["stretches"][0]["kind"] == "friction" and joints["index_pip"]["stretches"][0]["to"] == 100
    assert len(joints["index_pip"]["friction"]) == 20 and len(joints["index_pip"]["ref_friction"]) == 20
    assert joints["middle_mcp"]["status"] == "ok"
    listing = client.get("/api/sweeps").json()
    assert listing["reference"] == name and "results" not in listing["sweeps"][extra["saved"]]
    assert listing["sweeps"][extra["saved"]]["levels"]["index_pip"]["flex"]["n"] == 1
    assert client.post("/api/operation/tension_sweep/start",
                       json={"params": {"repeats": 6}}).status_code == 422


def test_estop_mid_sweep_releases_the_lease(client):
    client.post("/api/operation/tension_sweep/start", json={"params": {"step_duration_s": 0.5}})
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "maintenance")
    assert client.post("/api/estop").status_code == 200
    assert _wait_for(lambda: _operation(client).get("state") == "error")
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
    assert client.get("/api/sweeps").json()["sweeps"] == {}

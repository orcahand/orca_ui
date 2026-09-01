"""Wizard operation tests (simulated variant over the mock)."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.05}


def _wait_for(predicate, timeout=15.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client(tmp_path):
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _wait_awaiting(client, options, timeout=15.0):
    def check():
        snapshot = _operation(client) or {}
        return (snapshot.get("state") == "awaiting_input"
                and (snapshot.get("awaiting") or {}).get("options") == options)
    assert _wait_for(check, timeout=timeout), \
        f"never awaited {options}: {_operation(client)}"
    return _operation(client)


def _wait_op_state(client, state, timeout=20.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def test_wizard_two_full_rounds(client):
    response = client.post("/api/operation/wizard/start",
                           json={"params": {**FAST, "rounds": 2}})
    assert response.status_code == 200

    # Round 1: tension hold -> Release, calibrate runs, gate appears.
    _wait_awaiting(client, ["Release"])
    assert client.get("/api/status").json()["state"] == "maintenance"
    client.post("/api/operation/input", json={"value": "Release"})
    _wait_awaiting(client, ["Continue", "Finish"])
    client.post("/api/operation/input", json={"value": "Continue"})

    # Round 2: another hold -> Release, then done without a trailing gate.
    _wait_awaiting(client, ["Release"])
    client.post("/api/operation/input", json={"value": "Release"})
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"]["rounds_completed"] == 2

    assert _wait_for(
        lambda: client.get("/api/status").json()["state"] == "connected")


def test_wizard_estop_mid_round_releases_lease(client):
    client.post("/api/operation/wizard/start",
                json={"params": {**FAST, "rounds": 2}})
    _wait_awaiting(client, ["Release"])
    assert client.post("/api/estop").status_code == 200
    snapshot = _wait_op_state(client, "error")
    assert snapshot["detail"] == "stopped (e-stop)"
    assert _wait_for(
        lambda: client.get("/api/status").json()["state"] == "connected")

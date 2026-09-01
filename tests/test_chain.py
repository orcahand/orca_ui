"""configure_chain operation: validation guards (especially the reset
confirmation), the simulated assembly walk with its ``extra`` chain grid,
and the reset loop's stop flow — all over the real manager + mock stack."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.02}


def _wait_for(predicate, timeout=5.0, interval=0.02):
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
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"]
            == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _wait_state(client, state, timeout=10.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def test_reset_requires_explicit_confirmation(client):
    response = client.post("/api/operation/configure_chain/start",
                           json={"params": {"mode": "reset"}})
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"]

    # confirm must be the literal true — truthy strings don't count
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "reset", "confirm": "yes"}})
    assert response.status_code == 400


def test_configure_chain_blocked_while_operation_runs(client):
    # slow steps so the first op is guaranteed still running
    assert client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure",
                         "step_duration_s": 0.5}}).status_code == 200
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", **FAST}})
    assert response.status_code == 409
    client.post("/api/operation/stop")
    _wait_state(client, "done")

"""Cable-integrity stress test operation, over the mock hand."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


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


def _wait_op_state(client, state, timeout=30.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def _start(client, **params):
    return client.post("/api/operation/stress_test/start",
                       json={"params": params})


# ----- validation -----------------------------------------------------------


def test_needs_torque(client):
    response = _start(client, joints=["index_mcp"], cycles=1)
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


def test_rejects_a_margin_that_leaves_no_travel(client):
    assert client.post("/api/torque/enable").status_code == 200
    response = _start(client, joints=["index_mcp"], cycles=1, margin_deg=15.0)
    # The mock index_mcp spans well over 30°, so 15° a side still leaves
    # travel — the check is that an absurd margin is refused, not accepted.
    if response.status_code == 200:
        client.post("/api/operation/stop")
        _wait_op_state(client, "done")
    response = _start(client, joints=["index_mcp"], cycles=1, margin_deg=99.0)
    assert response.status_code == 400
    assert "margin_deg" in response.json()["detail"]


# ----- running ---------------------------------------------------------------


# ----- interpolation steps ---------------------------------------------------


def test_only_one_operation_at_a_time(client):
    assert client.post("/api/torque/enable").status_code == 200
    assert _start(client, joints=["index_mcp"], loop=True).status_code == 200
    _wait_op_state(client, "running")
    second = _start(client, joints=["ring_mcp"], cycles=1)
    assert second.status_code == 409
    client.post("/api/operation/stop")
    _wait_op_state(client, "done")

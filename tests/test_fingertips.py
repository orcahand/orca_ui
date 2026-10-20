"""number_fingertip operation: renumbering a fingertip is persistent, so it
writes only after an explicit confirmation and reports success only once the
fingertip answers at its new number after a power cycle. Runs over the real
manager + mock stack with orca_core's simulated connector board."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.operations import hand_ops
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client():
    hand_ops._simulated_fingertip_bus.clear()
    settings = UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False)
    with TestClient(create_app(settings)) as test_client:
        assert _wait_for(lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client
    hand_ops._simulated_fingertip_bus.clear()


def _operation(client):
    return client.get("/api/operation").json()["operation"] or {}


def _awaiting(client):
    assert _wait_for(lambda: _operation(client).get("state") == "awaiting_input"), _operation(client)
    return _operation(client)["awaiting"]


def _finished(client):
    assert _wait_for(lambda: _operation(client).get("state") in ("done", "error"))
    return _operation(client)


def test_numbering_needs_confirmation_and_verifies_after_power_cycle(client):
    read = {"params": {"mode": "detect"}}
    assert client.post("/api/operation/number_fingertip/start", json=read).status_code == 200
    seen = _finished(client)["extra"]
    assert (seen["found_modules"], seen["found_finger"], seen["fits"]) == ([2], "middle", [[0, "thumb"]])
    assert client.get("/api/status").json()["state"] == "connected"

    start = {"params": {"finger": "thumb", "mode": "number"}}

    assert client.post("/api/operation/number_fingertip/start", json=start).status_code == 200
    assert "module 2 to module 0" in _awaiting(client)["prompt"]
    client.post("/api/operation/input", json={"value": "Cancel"})
    assert _finished(client)["state"] == "done"
    assert hand_ops._simulated_fingertip_bus["state"].numbering.pending == {}
    assert client.get("/api/status").json()["state"] == "connected"

    assert client.post("/api/operation/number_fingertip/start", json=start).status_code == 200
    _awaiting(client)
    client.post("/api/operation/input", json={"value": "Set"})
    assert "Power-cycle" in _awaiting(client)["prompt"]
    client.post("/api/operation/input", json={"value": "Power-cycled"})
    done = _finished(client)
    assert done["state"] == "done", done
    assert done["extra"]["verified"] is True
    assert done["extra"]["found_modules"] == [0]

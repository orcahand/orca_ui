"""number_fingertip operation: renumbering a fingertip is persistent, so it
writes only after an explicit confirmation, never onto a number another
fingertip has, and reports success only once the fingertip answers at its new
number after a power cycle. Runs over the real manager + mock stack with
orca_core's simulated connector board."""

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


def _modules(op):
    return [tip["module"] for tip in op["extra"]["found"]]


def test_numbering_needs_confirmation_a_free_number_and_verifies_after_power_cycle(client):
    from orca_core.hardware.sensing.tactile_mock import TactileMockState

    bus = TactileMockState(connected_fingers=[])
    bus.numbering.modules = [1, 2]
    bus.numbering.parts = {1: "PXSR-CMDDP18B", 2: "PXSR-CMDDP18A"}
    hand_ops._simulated_fingertip_bus["state"] = bus

    read = {"params": {"mode": "detect"}}
    assert client.post("/api/operation/number_fingertip/start", json=read).status_code == 200
    seen = _finished(client)["extra"]
    assert seen["found"] == [
        {"module": 1, "finger": "index", "part": "PXSR-CMDDP18B", "fits": [1, 2, 3]},
        {"module": 2, "finger": "middle", "part": "PXSR-CMDDP18A", "fits": [0]},
    ]
    assert client.get("/api/status").json()["state"] == "connected"

    taken = {"params": {"finger": "index", "current_module": 2, "mode": "number"}}
    assert client.post("/api/operation/number_fingertip/start", json=taken).status_code == 200
    refused = _finished(client)
    assert refused["state"] == "error" and "taken" in refused["error"]
    assert bus.numbering.pending == {}

    start = {"params": {"finger": "thumb", "current_module": 2, "mode": "number"}}
    assert client.post("/api/operation/number_fingertip/start", json=start).status_code == 200
    assert "module 2 (middle) to module 0 (thumb)" in _awaiting(client)["prompt"]
    client.post("/api/operation/input", json={"value": "Cancel"})
    assert _finished(client)["state"] == "done"
    assert bus.numbering.pending == {}
    assert client.get("/api/status").json()["state"] == "connected"

    assert client.post("/api/operation/number_fingertip/start", json=start).status_code == 200
    _awaiting(client)
    client.post("/api/operation/input", json={"value": "Set"})
    assert "Power-cycle" in _awaiting(client)["prompt"]
    client.post("/api/operation/input", json={"value": "Power-cycled"})
    done = _finished(client)
    assert done["state"] == "done", done
    assert done["extra"]["verified"] is True
    assert _modules(done) == [0, 1]

"""REST + WebSocket integration tests over the mock hand."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=5.0, interval=0.05):
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
        test_client.config_path = config_path
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_status_reports_full_mock_capabilities(client):
    status = client.get("/api/status").json()
    caps = status["capabilities"]
    assert caps["motors"] and caps["tactile"] and caps["encoders"]
    assert status["torque_enabled"] is False


def test_target_without_torque_is_409(client):
    response = client.post("/api/joints/target",
                           json={"angles": {"index_mcp": 30.0}})
    assert response.status_code == 409


def test_ws_streams_measured_and_taxels(client):
    with client.websocket_connect("/ws") as ws:
        # First frames: status + control.state snapshots.
        first = json.loads(ws.receive_text())
        assert first["type"] in ("status", "control.state")

        ws.send_text(json.dumps({
            "type": "subscribe",
            "data": {"topics": ["joints.measured", "tactile.taxels",
                                "motors.telemetry"]},
        }))
        seen = {}
        deadline = time.time() + 5.0
        while time.time() < deadline and not (
                {"joints.measured", "tactile.taxels"} <= set(seen)):
            message = json.loads(ws.receive_text())
            seen.setdefault(message["type"], message)

        measured = seen["joints.measured"]["data"]["angles"]
        assert len(measured) == 17  # all encoder slots, wrist included
        assert "wrist" in measured
        taxels = seen["tactile.taxels"]["data"]["taxels"]
        assert len(taxels["index"]) == 87


def test_ws_command_moves_the_hand(client):
    seed = client.post("/api/torque/enable").json()["seed"]
    assert "index_mcp" in seed

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "subscribe", "data": {"topics": ["joints.measured"]}}))
        ws.send_text(json.dumps({
            "type": "cmd.joints.target",
            "data": {"angles": {"index_mcp": 45.0}}}))

        deadline = time.time() + 5.0
        converged = False
        while time.time() < deadline and not converged:
            message = json.loads(ws.receive_text())
            if message["type"] != "joints.measured":
                continue
            angle = message["data"]["angles"].get("index_mcp", 0.0)
            converged = abs(angle - 45.0) < 2.0
        assert converged

    client.post("/api/torque/disable")

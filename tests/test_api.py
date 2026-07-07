"""REST + WebSocket integration tests over the mock hand."""

import json
import os
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


def test_hand_info_and_geometry(client):
    info = client.get("/api/hand/info").json()
    assert len(info["joints"]) == 17
    geometry = client.get("/api/tactile/geometry").json()
    assert set(geometry) == {"thumb", "index", "middle", "ring", "pinky"}
    assert geometry["index"]["frame"] == "fingertip_local"
    assert len(geometry["index"]["positions"]) == 87
    assert geometry["index"]["source"] == "orca_ui_fallback"


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


def test_tactile_zero_persists_offsets(client):
    # Zeroing needs live frames; wait for the auto-started stream to produce.
    assert _wait_for(
        lambda: client.app.state.service.session.tactile_data() is not None)
    response = client.post("/api/tactile/zero", json={"num_samples": 5})
    assert response.status_code == 200
    calib_path = os.path.join(os.path.dirname(client.config_path),
                              "calibration.yaml")
    import yaml
    with open(calib_path) as f:
        calib = yaml.safe_load(f)
    assert "sensor_offsets" in calib
    assert client.post("/api/tactile/clear_zero").status_code == 200


def test_gains_endpoint_updates_control_state(client):
    response = client.post("/api/control/gains",
                           json={"kp": 1.5, "ki": 8.0,
                                 "correction_max_deg": 45.0})
    assert response.status_code == 200
    assert response.json()["control"]["gains"]["kp"] == 1.5


def test_model_metadata_hints_when_bundle_missing(client):
    response = client.get("/api/model/metadata")
    # Bundle may or may not be built at this point in history; both are valid,
    # but a missing bundle must return the build hint, not a blank 500.
    if response.status_code == 404:
        assert "build_hand_bundle" in response.json()["detail"]
    else:
        assert response.json()["urdf_url"].endswith("hand.urdf")


def test_mock_joint_sweep_endpoint(client):
    response = client.post("/api/mock/joint_sweep",
                           json={"joint": "index_mcp", "period_s": 0.5})
    assert response.status_code == 200
    assert response.json()["sweeping"] == "index_mcp"
    time.sleep(0.4)

    def moved():
        measured = client.app.state.service.session.measured_joints() or {}
        return abs(measured.get("index_mcp", 0.0)) > 5.0

    assert _wait_for(moved, timeout=3.0)
    response = client.post("/api/mock/joint_sweep", json={"joint": None})
    assert response.json()["sweeping"] is None

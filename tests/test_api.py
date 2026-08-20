"""REST + WebSocket integration tests over the mock hand."""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand import zeroing
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
    assert geometry["index"]["frame"] == "sensor"
    assert len(geometry["index"]["positions"]) == 87
    # Tactile session -> geometry comes from orca_core, normalized to mm.
    assert geometry["index"]["source"] == "orca_core"
    assert 1.0 < abs(geometry["index"]["positions"][0][1]) < 100.0

    mounts = client.get("/api/model/sensor_mounts").json()
    assert set(mounts) == {"thumb", "index", "middle", "ring", "pinky"}
    assert len(mounts["thumb"]["matrix"]) == 4


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
    # Mock sandboxes calibration writes into a throwaway dir (never the model
    # folder); offsets must land wherever the session's config points.
    session = client.app.state.service.session
    calib_path = session.hand.config.calibration_path
    assert os.path.dirname(calib_path) != os.path.dirname(client.config_path)
    import yaml
    with open(calib_path) as f:
        calib = yaml.safe_load(f)
    assert "sensor_offsets" in calib

    # The resultant baseline is persisted separately: it is one [fx, fy, fz]
    # per finger read off the resultant stream, not the sum of that finger's
    # taxel offsets (which would be tens of N on a 25.5 N full scale).
    resultants = calib["resultant_offsets"]
    for finger, vec in resultants.items():
        assert len(vec) == 3
        assert max(abs(v) for v in vec) < 26.0
        assert vec != [sum(axis) for axis in zip(*calib["sensor_offsets"][finger])]

    # One noise gate per taxel, measured from the same frames.
    gates = calib["taxel_noise_gates"]
    for finger, per_taxel in gates.items():
        assert len(per_taxel) == len(calib["sensor_offsets"][finger])
        assert all(g > 0 for g in per_taxel)

    # Restoring on reconnect applies all three, unchanged.
    zeroing.apply_saved_offsets(session)
    tactile = session.tactile_client
    assert tactile.taxel_offsets == calib["sensor_offsets"]
    assert tactile.resultant_offsets == resultants
    assert tactile.taxel_noise_gates == gates

    assert client.post("/api/tactile/clear_zero").status_code == 200
    assert tactile.taxel_offsets is None
    assert tactile.resultant_offsets is None
    assert tactile.taxel_noise_gates is None


def test_per_joint_gains_endpoints(client):
    listing = client.get("/api/control/gains").json()
    tunable = [entry["joint"] for entry in listing["joints"]]
    assert "wrist" in tunable  # the wrist is a loop joint like any other
    assert not any(entry["modified"] for entry in listing["joints"])
    joint = tunable[0]

    # Uniform gains: no "joints" key sets every loop joint at once.
    uniform = client.post("/api/control/gains",
                          json={"kp": 1.5, "ki": 8.0, "correction_max_deg": 45.0})
    assert uniform.status_code == 200
    assert uniform.json()["control"]["gains"]["kp"] == 1.5

    response = client.post("/api/control/gains",
                           json={"kp": 3.0, "ki": 2.0,
                                 "correction_max_deg": 20.0,
                                 "joints": [joint]})
    assert response.status_code == 200
    assert response.json()["control"]["joint_gains"][joint]["kp"] == 3.0
    entry = next(e for e in client.get("/api/control/gains").json()["joints"]
                 if e["joint"] == joint)
    assert entry == {"joint": joint, "modified": True, "kp": 3.0,
                     "ki": 2.0, "correction_max_deg": 20.0}

    # A joint with no PI channel has no gains to set.
    rejected = client.post("/api/control/gains",
                           json={"kp": 3.0, "ki": 2.0,
                                 "correction_max_deg": 20.0,
                                 "joints": ["nonexistent_joint"]})
    assert rejected.status_code == 400

    reset = client.post("/api/control/gains/reset", json={"joints": None})
    assert reset.status_code == 200
    assert (reset.json()["control"]["joint_gains"]
            == listing["config_gains"])


def test_model_metadata_serves_the_committed_bundle(client):
    """The bundle under orca_ui/models/hand_v2 is committed, so this is the
    only outcome; a 404 here means the asset went missing from the package."""
    response = client.get("/api/model/metadata")
    assert response.status_code == 200, response.text
    assert response.json()["urdf_url"].endswith("hand.urdf")


def test_mock_joint_sweep_endpoint(client):
    response = client.post("/api/mock/joint_sweep",
                           json={"joint": "index_mcp", "period_s": 0.5})
    assert response.status_code == 200
    assert response.json()["sweeping"] == "index_mcp"

    def moved():
        measured = client.app.state.service.session.measured_joints() or {}
        return abs(measured.get("index_mcp", 0.0)) > 5.0

    assert _wait_for(moved, timeout=3.0)
    response = client.post("/api/mock/joint_sweep", json={"joint": None})
    assert response.json()["sweeping"] is None


def test_spa_shell_is_revalidated_not_heuristically_cached(client):
    """index.html names the content-hashed bundle. Served without an explicit
    Cache-Control, browsers cache it heuristically and a soft reload after a
    rebuild silently keeps running the old JS."""
    response = client.get("/")
    if response.status_code == 503:
        pytest.skip("frontend not built")
    assert response.headers.get("cache-control") == "no-cache"


def test_stats_expose_the_command_feed(client):
    """The feed counter is how you tell interpolation is actually live: diff it
    during motion and it should climb at FEED_HZ, not the source rate."""
    from orca_ui.hand.commands import FEED_HZ

    command = client.get("/api/stats").json()["command"]
    assert command["feed_hz"] == FEED_HZ
    assert command["writes"] == 0
    assert command["ramping"] is False

    assert client.post("/api/torque/enable").status_code == 200
    assert client.post("/api/joints/target",
                       json={"angles": {"index_mcp": 12.0}}).status_code == 200
    assert _wait_for(
        lambda: client.get("/api/stats").json()["command"]["writes"] > 0)

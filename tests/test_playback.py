"""Record / replay / demo operation tests over the mock hand."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.operations import player
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


def _wait_op_state(client, state, timeout=15.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def _recorded_frames(client):
    """Frame count off the record op's detail line ("N frames · X.Xs")."""
    detail = (_operation(client) or {}).get("detail") or ""
    head = detail.split(" frames", 1)[0]
    return int(head) if head.isdigit() else 0


def _joint_ids(client):
    return [j["id"] for j in client.get("/api/hand/info").json()["joints"]]


def _synthetic_trajectory(client, name="synth", frames=150, freq=50.0,
                          joint="index_mcp", amplitude=30.0):
    """Craft a continuous recording that ramps one joint 0 -> amplitude."""
    service = client.app.state.service
    joint_ids = _joint_ids(client)
    idx = joint_ids.index(joint)
    rows = []
    for i in range(frames):
        row = [0.0] * len(joint_ids)
        row[idx] = amplitude * (i + 1) / frames
        rows.append(row)
    service.library.save_trajectory(name, {
        "metadata": {"type": "continuous", "created_at": "test",
                     "sampling_frequency_hz": freq,
                     "joint_ids": joint_ids, "hand_type": service.supervisor.config.type},
        "angles": rows,
    })
    return name


# ----- record ---------------------------------------------------------------------


def test_record_continuous_roundtrip_with_motion(client):
    service = client.app.state.service
    assert client.post("/api/torque/enable").status_code == 200

    # Drive motion below the arbiter (test-only): the record op owns the
    # control source, so service-level writes are rightly rejected while
    # it runs — the worker path is how we make the mock hand move anyway.
    moving = threading.Event()
    moving.set()

    def wiggle():
        t0 = time.monotonic()
        while moving.is_set():
            phase = (time.monotonic() - t0) % 2.0
            angle = 40.0 * (phase if phase < 1.0 else 2.0 - phase)
            service.worker.submit_targets({"index_mcp": angle})
            time.sleep(0.03)

    mover = threading.Thread(target=wiggle, daemon=True)
    mover.start()
    try:
        response = client.post("/api/operation/record/start", json={"params": {
            "mode": "continuous", "frequency": 60.0, "name": "wave",
            "disable_torque": False,
        }})
        assert response.status_code == 200
        # Stop as soon as enough frames are banked rather than sleeping a flat
        # second: faster here, and it still gets there on a loaded machine.
        assert _wait_for(lambda: _recorded_frames(client) >= 25), _operation(client)
        assert client.post("/api/operation/input",
                           json={"value": "save"}).status_code == 200
        snapshot = _wait_op_state(client, "done")
    finally:
        moving.clear()
        mover.join(timeout=2.0)

    assert snapshot["result"]["name"] == "wave"
    assert snapshot["result"]["frames"] >= 20
    listing = client.get("/api/trajectories").json()["trajectories"]
    assert listing[0]["name"] == "wave"

    # The recording captured actual motion, not a static pose.
    data = service.library.load_trajectory("wave")
    idx = _joint_ids(client).index("index_mcp")
    values = [row[idx] for row in data["angles"]]
    assert max(values) - min(values) > 5.0

    # ...and it replays: the mock loop converges toward the last frame.
    assert client.post("/api/operation/replay/start", json={"params": {
        "name": "wave", "speed": 2.0}}).status_code == 200
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"]["frames"] == len(values)

    def converged():
        measured = service.session.measured_joints() or {}
        return abs(measured.get("index_mcp", 1e9) - values[-1]) < 6.0
    assert _wait_for(converged), "replay did not converge to the last frame"


def _motor_only_config():
    """Mock model copy with the encoder and tactile blocks removed."""
    import yaml

    config_path = materialize_mock_model()
    with open(config_path) as f:
        data = yaml.safe_load(f)
    for key in ("use_joint_feedback", "joint_encoder_joints",
                "encoder_serial_port", "sensors"):
        data.pop(key, None)
    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return config_path


# ----- replay ---------------------------------------------------------------------


def test_replay_requires_torque(client):
    _synthetic_trajectory(client)
    response = client.post("/api/operation/replay/start",
                           json={"params": {"name": "synth"}})
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


def test_replay_rejects_joint_order_mismatch(client):
    service = client.app.state.service
    joint_ids = list(reversed(_joint_ids(client)))
    service.library.save_trajectory("mismatched", {
        "metadata": {"type": "continuous", "sampling_frequency_hz": 50.0,
                     "joint_ids": joint_ids, "hand_type": None},
        "angles": [[0.0] * len(joint_ids)],
    })
    client.post("/api/torque/enable")
    response = client.post("/api/operation/replay/start",
                           json={"params": {"name": "mismatched"}})
    assert response.status_code == 400
    assert "joint order" in response.json()["detail"]


def _segment_seconds(travel_deg):
    return max(travel_deg / player.WAYPOINT_SPEED_DEG_S, player.MIN_SEGMENT_S)


# ----- demo -----------------------------------------------------------------------


def test_demo_auto_enables_and_restores_torque(client):
    # Scripts always run: torque off is no blocker — the demo enables it for
    # the run and, because it was off before, turns it back off afterwards.
    assert client.get("/api/status").json()["torque_enabled"] is False
    response = client.post("/api/operation/demo/start",
                           json={"params": {"name": "open_close"}})
    assert response.status_code == 200
    assert _wait_for(
        lambda: client.get("/api/status").json()["torque_enabled"])
    _wait_op_state(client, "done", timeout=30.0)
    assert _wait_for(
        lambda: client.get("/api/status").json()["torque_enabled"] is False)

    log = client.get("/api/operation/log").json()
    assert any("enabling it for the script" in e["line"]
               for e in log["lines"])
    assert any("torque back off" in e["line"] for e in log["lines"])

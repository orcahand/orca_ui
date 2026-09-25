"""Endurance recorder: it adds no bus reads, and the page's contract holds.

The recorder's per-reversal samples are the read the waypoint hold already
makes — one transaction for positions and currents. A recorder that polled
on its own would land group reads on a half-duplex bus mid-motion, so the
first test pins the hold to exactly its own polls. The second runs the real
thing over a motors-plus-tactile mock (the endurance rig's shape) and checks
the REST shapes the Stats page reads, including the CSV download.
"""

import time

import pytest
import yaml
from fastapi.testclient import TestClient

from orca_ui.hand import endurance
from orca_ui.hand.operations import player
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=20.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# ----- the hold's read is the sample --------------------------------------------


class _Session:
    """Motors-only session stand-in: arrives on the first poll."""

    def __init__(self, angles):
        self.reads = 0
        self._angles = angles

    def sampled_state(self):
        self.reads += 1
        return dict(self._angles), {1: 120.0, 2: 45.5}


class _Ctx:
    def __init__(self, service):
        self.service = service

    def sleep(self, seconds):
        pass

    def check_stop(self):
        pass

    def pause_point(self):
        pass


class _Service:
    def __init__(self, session, recorder):
        self.session = session
        self.endurance = recorder


def test_a_hold_records_its_own_read_and_makes_no_extra_ones(tmp_path):
    calibration = tmp_path / "calibration.yaml"
    calibration.write_text("")
    recorder = endurance.EnduranceRecorder(
        endurance.recorder_path(str(calibration)), str(calibration),
        joints=["index_mcp", "index_pip"], motors=[1, 2],
        motor_joint={1: "index_mcp", 2: "index_pip"}, fingers=["index"])
    angles = {"index_mcp": 30.0, "index_pip": 10.0}
    session = _Session(angles)
    ctx = _Ctx(_Service(session, recorder))

    # No test running: the hold still polls exactly as before, nothing lands.
    player._hold_until_arrived(ctx, angles, cycle=1, leg=0)
    assert session.reads == 1
    assert recorder.snapshot()["tests"] == []

    test = recorder.start("bench")
    session.reads = 0
    player._hold_until_arrived(ctx, angles, cycle=3, leg=1)
    assert session.reads == 1, "the recorder must not read the bus itself"

    full = recorder.test(test["id"])
    assert full["samples"] == 1
    latest = full["latest"]
    assert latest["cycle"] == 3 and latest["leg"] == 1
    assert latest["angles"] == {"index_mcp": 30.0, "index_pip": 10.0}
    assert latest["currents"] == {"1": 120.0, "2": 45.5}
    buckets = full["buckets"]
    assert buckets["angle_min"]["index_mcp"] == [30.0]
    assert buckets["current_mean"]["2"] == [45.5]
    recorder.save()
    rows = open(recorder.samples_path(test["id"])).read().splitlines()
    assert rows[0].startswith("t_s,run_id,cycle,cycle_total,leg,angle_deg:index_mcp")
    assert rows[1].split(",")[2:5] == ["3", "3", "1"]


# ----- the page's contract over a motors + tactile mock -------------------------


def _motors_and_tactile_config():
    config_path = materialize_mock_model()
    with open(config_path) as f:
        data = yaml.safe_load(f)
    for key in ("use_joint_feedback", "joint_encoder_joints",
                "encoder_serial_port"):
        data.pop(key, None)
    with open(config_path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    return config_path


@pytest.fixture()
def client(tmp_path):
    settings = UiSettings(config_path=_motors_and_tactile_config(), mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_endurance_api_shapes_over_a_looping_replay(client):
    service = client.app.state.service
    joint_ids = list(service.supervisor.config.joint_ids)
    idx = joint_ids.index("index_mcp")
    open_pose = [0.0] * len(joint_ids)
    closed = list(open_pose)
    closed[idx] = 25.0
    service.library.save_trajectory("grip", {
        "metadata": {"type": "discrete_waypoints", "created_at": "test",
                     "joint_ids": joint_ids,
                     "hand_type": service.supervisor.config.type},
        "waypoints": [open_pose, closed],
    })
    assert client.post("/api/torque/enable").status_code == 200

    started = client.post("/api/endurance/tests", json={"label": "rig"})
    assert started.status_code == 200
    test_id = started.json()["id"]
    assert client.post("/api/endurance/tests").status_code == 409

    assert client.post("/api/operation/replay/start", json={"params": {
        "name": "grip", "speed": 2.0, "loop": True}}).status_code == 200
    assert _wait_for(
        lambda: client.get(f"/api/endurance/tests/{test_id}").json()["samples"] >= 4)
    assert client.post("/api/endurance/tests/{}/note".format(test_id),
                       json={"text": "checked the thumb"}).status_code == 200
    assert client.post("/api/operation/stop").status_code == 200
    assert _wait_for(lambda: (client.get("/api/operation").json()["operation"]
                              or {}).get("state") == "done")
    def replay_closed():
        return any(e["kind"] == "operation" and "cycle" in e["detail"]
                   for e in client.get(f"/api/endurance/tests/{test_id}").json()["events"])
    assert _wait_for(replay_closed), client.get(
        f"/api/endurance/tests/{test_id}").json()["events"]

    full = client.get(f"/api/endurance/tests/{test_id}").json()
    assert full["active"] and full["joints"] == joint_ids
    assert full["motors"] and full["fingers"]
    latest = full["latest"]
    assert latest["leg"] in (0, 1, 2) and latest["cycle"] >= 1
    assert set(latest["angles"]) == set(joint_ids)
    assert set(latest["currents"]) == {str(m) for m in full["motors"]}
    assert set(latest["forces"]) == set(full["fingers"])
    buckets = full["buckets"]
    assert len(buckets["t0"]) == len(buckets["n"]) >= 1
    assert set(buckets["angle_min"]) == set(joint_ids)
    assert len(buckets["current_mean"][str(full["motors"][0])]) == len(buckets["t0"])
    kinds = {(e["kind"], e["subject"]) for e in full["events"]}
    assert ("operation", "replay") in kinds and ("note", "operator") in kinds
    assert full["runs"][-1]["kind"] == "replay" and full["runs"][-1]["ended_t"]
    assert full["checkpoints"] == []

    csv = client.get(f"/api/endurance/tests/{test_id}/samples.csv")
    assert csv.status_code == 200
    lines = csv.text.splitlines()
    assert lines[0].split(",")[:5] == ["t_s", "run_id", "cycle", "cycle_total", "leg"]
    assert len(lines) - 1 == full["samples"]

    # The liveness verdicts the Sensor Health panel now reads.
    health = client.app.state.telemetry._sensor_health.payload(service.session)
    fingers = health["tactile"]["fingers"]
    assert all("verdict" in f for f in fingers.values())

    assert client.post(f"/api/endurance/tests/{test_id}/stop").status_code == 200
    listing = client.get("/api/endurance").json()
    assert listing["active_id"] is None
    assert listing["tests"][0]["id"] == test_id and not listing["tests"][0]["active"]
    assert client.delete(f"/api/endurance/tests/{test_id}").status_code == 200
    assert client.get(f"/api/endurance/tests/{test_id}").status_code == 404

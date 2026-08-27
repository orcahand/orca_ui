"""JointUsageTracker sessions/motion-gating/health + the /api/usage endpoints."""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.usage_stats import (
    DEADBAND_DEG,
    NUM_BINS,
    JointUsageTracker,
    stats_path,
)
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

ROMS = {"index_mcp": [0.0, 100.0]}


@pytest.fixture()
def tracker(tmp_path):
    return JointUsageTracker(str(tmp_path / "joint_usage.json"), ROMS)


def _joint(tracker, name="index_mcp"):
    return tracker.snapshot()["sessions"][-1]["joints"][name]


def test_travel_and_histogram_accumulate(tracker):
    # 0 -> 49° in 1° steps at 50 Hz: 49° of travel, all forward.
    for i in range(50):
        tracker.feed({"index_mcp": float(i)}, now=100.0 + i * 0.02)
    stats = _joint(tracker)
    assert stats["travel_deg"] == pytest.approx(49.0, abs=1.0)
    assert stats["reversals"] == 0
    assert stats["max_deg"] == 49.0
    assert stats["moving_s"] == pytest.approx(0.98, abs=0.1)
    # Only the lower half of the ROM was visited.
    hist = stats["hist"]
    assert sum(hist[NUM_BINS // 2:]) == 0
    assert sum(hist[:NUM_BINS // 2]) > 0


def test_static_hand_logs_nothing(tracker):
    # Torque on, position held under a standing command: the identical angle
    # streams for minutes — nothing may accumulate, not even observed time.
    for i in range(6000):
        tracker.feed({"index_mcp": 42.0}, now=100.0 + i * 0.02)
    assert tracker.snapshot()["sessions"][-1]["joints"] == {}


def test_noise_below_deadband_is_not_logged(tracker):
    jitter = DEADBAND_DEG * 0.4
    for i in range(200):
        angle = 20.0 + (jitter if i % 2 else -jitter)
        tracker.feed({"index_mcp": angle}, now=100.0 + i * 0.02)
    assert tracker.snapshot()["sessions"][-1]["joints"] == {}


def test_dwell_counts_only_around_movement(tracker):
    # One real 5° move, then parked for 100 s: dwell time stops accruing
    # ACTIVE_LINGER_S after the move.
    tracker.feed({"index_mcp": 0.0}, now=100.0)
    tracker.feed({"index_mcp": 5.0}, now=100.5)
    for i in range(200):
        tracker.feed({"index_mcp": 5.0}, now=101.0 + i * 0.5)
    stats = _joint(tracker)
    assert stats["travel_deg"] == pytest.approx(5.0, abs=0.1)
    assert stats["observed_s"] < 2.5


def test_reversals_count_direction_changes(tracker):
    now = 100.0
    # 3 full open/close cycles of 20° -> 5 direction changes.
    for cycle in range(3):
        for step in list(range(21)) + list(range(20, -1, -1)):
            tracker.feed({"index_mcp": float(step)}, now=now)
            now += 0.02
    stats = _joint(tracker)
    assert stats["reversals"] == 5
    assert stats["travel_deg"] == pytest.approx(120.0, abs=3.0)


def test_gap_is_not_travel(tracker):
    tracker.feed({"index_mcp": 0.0}, now=100.0)
    tracker.feed({"index_mcp": 1.0}, now=100.02)
    # 700 s silence, hand comes back at a very different pose: the jump is
    # a re-anchor, not 89° of travel.
    tracker.feed({"index_mcp": 90.0}, now=800.0)
    assert _joint(tracker)["travel_deg"] == pytest.approx(1.0, abs=0.1)


def test_sessions_create_delete_rename(tracker):
    tracker.feed({"index_mcp": 0.0}, now=100.0)
    tracker.feed({"index_mcp": 10.0}, now=100.2)
    first_id = tracker.snapshot()["current_id"]

    # There is always a running session, auto-named for later renaming.
    assert tracker.snapshot()["sessions"][-1]["label"] == "session 1"

    second_id = tracker.new_session(label="wear test")
    assert second_id != first_id
    tracker.feed({"index_mcp": 10.0}, now=200.0)
    tracker.feed({"index_mcp": 30.0}, now=200.4)

    snapshot = tracker.snapshot()
    assert [s["id"] for s in snapshot["sessions"]] == [first_id, second_id]
    assert snapshot["sessions"][0]["ended_at"] is not None
    assert snapshot["sessions"][0]["joints"]["index_mcp"]["travel_deg"] == \
        pytest.approx(10.0, abs=0.5)
    assert snapshot["sessions"][1]["label"] == "wear test"
    assert snapshot["sessions"][1]["joints"]["index_mcp"]["travel_deg"] == \
        pytest.approx(20.0, abs=0.5)

    assert tracker.rename_session(first_id, "baseline")
    assert tracker.snapshot()["sessions"][0]["label"] == "baseline"

    # Deleting a closed session keeps the current one running.
    assert tracker.delete_session(first_id)
    snapshot = tracker.snapshot()
    assert [s["id"] for s in snapshot["sessions"]] == [second_id]

    # Deleting the current session starts a fresh auto-named one.
    assert tracker.delete_session(second_id)
    snapshot = tracker.snapshot()
    assert len(snapshot["sessions"]) == 1
    assert snapshot["sessions"][0]["joints"] == {}
    assert snapshot["sessions"][0]["label"] == "session 2"
    assert not tracker.delete_session("nope")


def test_persistence_roundtrip(tracker, tmp_path):
    for i in range(11):
        tracker.feed({"index_mcp": float(i)}, now=100.0 + i * 0.02)
    tracker.new_session(label="second")
    tracker.save()

    reloaded = JointUsageTracker(str(tmp_path / "joint_usage.json"), ROMS)
    snapshot = reloaded.snapshot()
    assert len(snapshot["sessions"]) == 2
    assert snapshot["sessions"][0]["joints"]["index_mcp"]["travel_deg"] == \
        pytest.approx(10.0, abs=0.5)
    assert snapshot["sessions"][1]["label"] == "second"


def test_v1_file_migrates_into_a_session(tmp_path):
    path = tmp_path / "joint_usage.json"
    joints = {"index_mcp": {
        "rom": [0.0, 100.0], "travel_deg": 123.0, "moving_s": 4.0,
        "observed_s": 5.0, "hist": [0.0] * NUM_BINS, "min_deg": 1.0,
        "max_deg": 2.0, "reversals": 3, "max_speed_dps": 10.0,
        "first_seen": None, "last_active": None}}
    path.write_text(json.dumps({
        "schema": 1, "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": None, "sessions": 4, "joints": joints}))
    tracker = JointUsageTracker(str(path), ROMS)
    snapshot = tracker.snapshot()
    assert len(snapshot["sessions"]) == 2
    assert snapshot["sessions"][0]["label"] == "imported"
    assert snapshot["sessions"][0]["joints"]["index_mcp"]["travel_deg"] == 123.0
    assert snapshot["sessions"][1]["joints"] == {}
    assert snapshot["sessions"][1]["label"] == "session 1"


def test_health_transitions_and_downtime(tracker):
    caps = SimpleNamespace(motors=True)
    healthy = {
        "encoders": {"joints": {"index_mcp": {"verdict": "live"}}},
        "tactile": {"fingers": {"index": {"connected": True}}},
        "links": {"encoders": {"connected": True, "port_dead": False}},
    }
    broken = json.loads(json.dumps(healthy))
    broken["tactile"]["fingers"]["index"]["connected"] = False
    broken["encoders"]["joints"]["index_mcp"]["verdict"] = "no frames"

    tracker.feed_health(healthy, caps, now=100.0)
    health = tracker.snapshot()["sessions"][-1]["health"]
    assert health["events"] == []   # coming up healthy is not an event

    tracker.feed_health(broken, caps, now=101.0)
    tracker.feed_health(broken, caps, now=102.0)
    tracker.feed_health(healthy, caps, now=103.0)
    health = tracker.snapshot()["sessions"][-1]["health"]
    subjects = [(e["subject"], e["to"]) for e in health["events"]]
    assert ("tactile:index", "down") in subjects
    assert ("encoder:index_mcp", "no frames") in subjects
    assert ("tactile:index", "up") in subjects
    assert ("encoder:index_mcp", "live") in subjects
    # Downtime: unhealthy across the 101->102 and 102->103 windows.
    assert health["down_s"]["tactile:index"] == pytest.approx(2.0, abs=0.1)
    assert health["down_s"]["encoder:index_mcp"] == pytest.approx(2.0, abs=0.1)
    assert "motors" not in health["down_s"]
    assert health["observed_s"] == pytest.approx(3.0, abs=0.1)


def test_usage_endpoints(tmp_path):
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as client:
        deadline = time.time() + 10
        while time.time() < deadline:
            if client.get("/api/status").json()["state"] == "connected":
                break
            time.sleep(0.05)
        snapshot = client.get("/api/usage/stats").json()
        assert snapshot["bins"] == NUM_BINS
        assert snapshot["path"].endswith("joint_usage.json")
        assert len(snapshot["sessions"]) >= 1
        first_id = snapshot["current_id"]

        # The mock streams a STATIC pose: motion stats must stay empty.
        assert snapshot["sessions"][-1]["joints"] == {}

        created = client.post("/api/usage/session",
                              json={"label": "test run"}).json()
        assert created["ok"] and created["id"] != first_id
        assert client.put(f"/api/usage/session/{created['id']}",
                          json={"label": "renamed"}).status_code == 200
        snapshot = client.get("/api/usage/stats").json()
        assert snapshot["current_id"] == created["id"]
        assert snapshot["sessions"][-1]["label"] == "renamed"

        assert client.delete(
            f"/api/usage/session/{first_id}").status_code == 200
        assert client.delete(
            "/api/usage/session/missing").status_code == 404
        assert client.post("/api/usage/reset").status_code == 200
        snapshot = client.get("/api/usage/stats").json()
        assert len(snapshot["sessions"]) == 1
        assert snapshot["sessions"][0]["joints"] == {}


def test_stats_path_sits_next_to_calibration(tmp_path):
    assert stats_path(str(tmp_path / "calibration.yaml")) == \
        str(tmp_path / "joint_usage.json")

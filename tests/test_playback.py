"""Record / replay / demo operation tests over the mock hand."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.operations import player
from orca_ui.hand.operations.player import _interpolate
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


def test_record_default_disables_torque_and_keeps_it_off(client):
    assert client.post("/api/torque/enable").status_code == 200
    client.post("/api/operation/record/start", json={"params": {
        "mode": "continuous", "frequency": 30.0, "name": "posed"}})
    assert _wait_for(
        lambda: client.get("/api/status").json()["torque_enabled"] is False)

    # Server-side gate: a second client can't re-enable torque mid-record.
    response = client.post("/api/torque/enable")
    assert response.status_code == 409
    assert "record" in response.json()["detail"]

    time.sleep(0.3)
    client.post("/api/operation/input", json={"value": "save"})
    _wait_op_state(client, "done")
    # Torque is NEVER re-enabled by record.
    assert client.get("/api/status").json()["torque_enabled"] is False


def test_record_waypoints_via_input(client):
    client.post("/api/operation/record/start", json={"params": {
        "mode": "waypoints", "name": "keyframes"}})
    _wait_op_state(client, "awaiting_input")
    for _ in range(2):
        assert client.post("/api/operation/input",
                           json={"value": "Capture"}).status_code == 200
        _wait_op_state(client, "awaiting_input")
    client.post("/api/operation/input", json={"value": "Stop & save"})
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"]["frames"] == 2
    assert snapshot["result"]["type"] == "discrete_waypoints"


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


@pytest.fixture()
def motor_only_client(tmp_path):
    settings = UiSettings(config_path=_motor_only_config(), mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_record_motor_only_uses_the_calibrated_estimate(motor_only_client):
    """A hand without encoders records from the motor-derived estimate."""
    client = motor_only_client
    caps = client.get("/api/status").json()["capabilities"]
    assert caps["motors"] and not caps["encoders"]

    client.post("/api/operation/record/start", json={"params": {
        "mode": "waypoints", "name": "motor_only"}})
    _wait_op_state(client, "awaiting_input")
    assert client.post("/api/operation/input",
                       json={"value": "Capture"}).status_code == 200
    _wait_op_state(client, "awaiting_input")
    client.post("/api/operation/input", json={"value": "Stop & save"})
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"]["frames"] == 1

    service = client.app.state.service
    saved = service.library.load_trajectory("motor_only")
    assert saved["metadata"]["joint_source"] == "motors"


def test_record_motor_only_requires_calibration(motor_only_client, monkeypatch):
    """Without encoders AND without calibration there is no joint source."""
    client = motor_only_client
    session = client.app.state.service.session
    monkeypatch.setattr(type(session.hand), "is_calibrated",
                        lambda self, **kwargs: False)
    session._estimate_ok = None  # drop the cached calibration check
    response = client.post("/api/operation/record/start", json={"params": {
        "mode": "continuous", "name": "nope"}})
    assert response.status_code == 409
    assert "calibration" in response.json()["detail"]


def test_record_duplicate_name_rejected(client):
    _synthetic_trajectory(client, name="taken")
    response = client.post("/api/operation/record/start", json={"params": {
        "mode": "continuous", "name": "taken"}})
    assert response.status_code == 409


def test_plain_stop_aborts_recording_without_saving(client):
    client.post("/api/operation/record/start", json={"params": {
        "mode": "continuous", "frequency": 30.0, "name": "aborted"}})
    assert _wait_for(
        lambda: (_operation(client) or {}).get("phase") == "recording")
    client.post("/api/operation/stop")
    snapshot = _wait_op_state(client, "done")
    assert snapshot["detail"] == "stopped"
    names = [t["name"] for t in
             client.get("/api/trajectories").json()["trajectories"]]
    assert "aborted" not in names


# ----- replay ---------------------------------------------------------------------


def test_replay_requires_torque(client):
    _synthetic_trajectory(client)
    response = client.post("/api/operation/replay/start",
                           json={"params": {"name": "synth"}})
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


def test_replay_rejects_bad_speed_and_missing_file(client):
    _synthetic_trajectory(client)
    client.post("/api/torque/enable")
    assert client.post("/api/operation/replay/start", json={"params": {
        "name": "synth", "speed": 3.0}}).status_code == 400
    assert client.post("/api/operation/replay/start", json={"params": {
        "name": "missing"}}).status_code == 404


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


def test_replay_pause_resume_and_slider_gating(client):
    _synthetic_trajectory(client, frames=300, freq=50.0)   # 6 s at x1
    client.post("/api/torque/enable")
    client.post("/api/operation/replay/start",
                json={"params": {"name": "synth"}})
    _wait_op_state(client, "running")

    # Sliders are locked out, naming the owner.
    response = client.post("/api/joints/target",
                           json={"angles": {"index_mcp": 0.0}})
    assert response.status_code == 409
    assert "replay" in response.json()["detail"]

    assert client.post("/api/operation/pause").status_code == 200
    _wait_op_state(client, "paused")
    assert client.post("/api/operation/resume").status_code == 200
    _wait_op_state(client, "running")

    client.post("/api/operation/stop")
    _wait_op_state(client, "done")
    # Control returns to manual.
    assert client.post("/api/joints/target",
                       json={"angles": {"index_mcp": 0.0}}).status_code == 200


def _waypoint_trajectory(client, name, waypoints):
    service = client.app.state.service
    joint_ids = _joint_ids(client)
    service.library.save_trajectory(name, {
        "metadata": {"type": "discrete_waypoints", "created_at": "test",
                     "joint_ids": joint_ids,
                     "hand_type": service.supervisor.config.type},
        "waypoints": waypoints,
    })
    return joint_ids


def _segment_frames(travel_deg):
    """Frames the player synthesizes for one segment, derived not hardcoded."""
    return int(_segment_seconds(travel_deg) * player.WAYPOINT_RATE_HZ) + 1


def _segment_seconds(travel_deg):
    return max(travel_deg / player.WAYPOINT_SPEED_DEG_S, player.MIN_SEGMENT_S)


def test_interpolate_paces_segments_by_travel():
    # 60 deg of travel at the cruise speed -> a 1 s segment, plus the opening
    # frame that sits on the first waypoint so it can be held like the rest.
    frames, rate, holds = _interpolate([[0.0, 0.0], [60.0, 0.0]])
    assert rate == player.WAYPOINT_RATE_HZ
    assert len(frames) == _segment_frames(60.0)
    # A tiny adjustment still glides over the minimum segment duration.
    tiny, _, _ = _interpolate([[0.0, 0.0], [0.5, 0.0]])
    assert len(tiny) == int(player.MIN_SEGMENT_S * player.WAYPOINT_RATE_HZ) + 1
    # None (unrecorded joint) passes through untouched.
    sparse, _, _ = _interpolate([[0.0, None], [60.0, None]])
    assert all(row[1] is None for row in sparse)
    # Every waypoint is a frame the player can stop on, first one included.
    assert holds == [0, len(frames) - 1]
    assert frames[0] == [0.0, 0.0] and frames[-1] == [60.0, 0.0]
    # A single captured pose is still one holdable frame.
    assert _interpolate([[5.0, 0.0]]) == ([[5.0, 0.0]], player.WAYPOINT_RATE_HZ, [0])


def test_looped_waypoint_replay_closes_the_cycle(client):
    """Looping a 2-pose recording synthesizes the return segment, so both
    directions play at the same speed instead of snapping back."""
    joint_ids = _joint_ids(client)
    closed = [0.0] * len(joint_ids)
    closed[joint_ids.index("index_mcp")] = 60.0
    opened = [0.0] * len(joint_ids)
    _waypoint_trajectory(client, "ring2", [closed, opened])
    client.post("/api/torque/enable")

    # One-shot: a single 1 s segment (60 deg at cruise speed), plus the
    # opening frame on the first waypoint.
    client.post("/api/operation/replay/start",
                json={"params": {"name": "ring2"}})
    snapshot = _wait_op_state(client, "done")
    one_way = snapshot["result"]["frames"]
    assert one_way == _segment_frames(60.0)

    # Looped: the return glide doubles the cycle.
    client.post("/api/operation/replay/start",
                json={"params": {"name": "ring2", "loop": True}})
    detail = _wait_for(lambda: (
        d := ((_operation(client) or {}).get("detail") or ""))
        and "@" in d and d)
    assert f"{2 * _segment_seconds(60.0):.1f}s" in detail, detail
    client.post("/api/operation/stop")
    _wait_op_state(client, "done")


def test_replay_glides_to_the_first_frame(client):
    """Playback approaches the start pose instead of jumping at motor speed."""
    joint_ids = _joint_ids(client)
    away = [0.0] * len(joint_ids)
    away[joint_ids.index("index_mcp")] = 50.0
    _waypoint_trajectory(client, "faraway", [away, [0.0] * len(joint_ids)])
    client.post("/api/torque/enable")
    client.post("/api/operation/replay/start",
                json={"params": {"name": "faraway"}})
    assert _wait_for(
        lambda: (_operation(client) or {}).get("phase") == "approach"), \
        _operation(client)
    _wait_op_state(client, "done")


def test_waypoint_replay_holds_at_every_waypoint(client):
    """Each captured pose is held until the hand arrives, so playback cannot
    round the corner and miss the pose the way it did open-loop."""
    joint_ids = _joint_ids(client)
    closed = [0.0] * len(joint_ids)
    closed[joint_ids.index("index_mcp")] = 60.0
    _waypoint_trajectory(client, "held", [[0.0] * len(joint_ids), closed])
    client.post("/api/torque/enable")

    started = time.monotonic()
    client.post("/api/operation/replay/start", json={"params": {"name": "held"}})
    snapshot = _wait_op_state(client, "done")
    elapsed = time.monotonic() - started

    motion_s = snapshot["result"]["duration_s"]
    # duration_s stays the commanded motion; the two holds sit on top of it.
    assert motion_s == pytest.approx(
        _segment_seconds(60.0) + 1.0 / player.WAYPOINT_RATE_HZ, abs=0.05)
    assert elapsed >= motion_s + 2 * player.DWELL_MIN_S
    # The mock plant settles well inside the cap, so neither hold runs long.
    assert elapsed < motion_s + 2 * player.DWELL_MAX_S + 1.0

    log = client.get("/api/operation/log").json()["lines"]
    assert any("holding at 2 waypoint(s)" in entry["line"] for entry in log), log


def test_continuous_replay_does_not_hold(client):
    """A continuous recording carries its own timing — nothing to hold."""
    _synthetic_trajectory(client, name="cont", frames=25, freq=50.0)  # 0.5 s
    client.post("/api/torque/enable")
    started = time.monotonic()
    client.post("/api/operation/replay/start", json={"params": {"name": "cont"}})
    _wait_op_state(client, "done")
    elapsed = time.monotonic() - started

    # On the mechanism, not the clock: the waypoint path logs its holds.
    log = client.get("/api/operation/log").json()["lines"]
    assert not any("holding at" in entry["line"] for entry in log), log
    # ...and it still finishes in about the recording's own duration.
    assert elapsed < 0.5 + player.DWELL_MAX_S


def test_replay_glides_to_the_first_frame_without_encoders(motor_only_client):
    """The approach glide reads the joint source, not the encoders: on a
    motor-only hand it used to come back empty and playback stepped to the
    first waypoint at motor speed."""
    client = motor_only_client
    joint_ids = _joint_ids(client)
    away = [0.0] * len(joint_ids)
    away[joint_ids.index("index_mcp")] = 50.0
    _waypoint_trajectory(client, "faraway", [away, [0.0] * len(joint_ids)])
    client.post("/api/torque/enable")
    client.post("/api/operation/replay/start",
                json={"params": {"name": "faraway"}})
    assert _wait_for(
        lambda: (_operation(client) or {}).get("phase") == "approach"), \
        _operation(client)
    _wait_op_state(client, "done")


# ----- demo -----------------------------------------------------------------------


def test_demo_plays_builtin_sequence(client):
    client.post("/api/torque/enable")
    response = client.post("/api/operation/demo/start",
                           json={"params": {"name": "open_close"}})
    assert response.status_code == 200
    snapshot = _wait_op_state(client, "done", timeout=30.0)
    assert snapshot["result"]["frames"] > 0


def test_demo_unknown_name_404(client):
    client.post("/api/torque/enable")
    assert client.post("/api/operation/demo/start", json={"params": {
        "name": "macarena"}}).status_code == 404


def test_demo_loop_runs_until_stopped(client):
    client.post("/api/torque/enable")
    response = client.post("/api/operation/demo/start", json={"params": {
        "name": "open_close", "loop": True}})
    assert response.status_code == 200
    _wait_op_state(client, "running")
    # Still running well past a couple of progress updates — it loops.
    time.sleep(1.0)
    assert (_operation(client) or {}).get("state") == "running"
    client.post("/api/operation/stop")
    snapshot = _wait_op_state(client, "done")
    assert snapshot["detail"] == "stopped"
    # Control returns to manual afterwards.
    assert client.post("/api/joints/target",
                       json={"angles": {"index_mcp": 0.0}}).status_code == 200

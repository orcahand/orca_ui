"""Teleop subsystem tests: ingress protocol, arbiter integration, ramp,
watchdog, e-stop, and the managed-child runner.

A synthetic client drives the real ``/ws/teleop`` wire protocol over the
TestClient (external mode), so CI needs no orca_teleop environment.
"""

import math
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orca_ui.hand.operations import Operation
from orca_ui.hand.states import ControlSource
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T


def _wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


class FastOp(Operation):
    kind = "test.fast"

    def run(self, ctx):
        return {"ok": True}


class HoldOp(Operation):
    kind = "test.hold"
    control_source = ControlSource.OPERATION

    def run(self, ctx):
        while True:
            ctx.sleep(0.05)


@pytest.fixture()
def client():
    config_path = materialize_mock_model()
    settings = UiSettings(
        config_path=config_path, mock=True, open_browser=False,
        # Fast watchdog so loss/auto-disengage tests stay quick.
        teleop_hold_after_ms=100, teleop_disengage_after_s=0.6,
    )
    app = create_app(settings)
    for op_cls in (FastOp, HoldOp):
        app.state.operations.register(op_cls)
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _hub_payload(client, topic):
    entry = client.app_state.hub.latest(topic)
    return entry[2] if entry else None


def _teleop_state(client):
    return client.get("/api/teleop/state").json()["session"]


def _control(client):
    return client.get("/api/hand/info").json()["control"]


class SyntheticChild:
    """Drives the child side of the wire protocol over the TestClient."""

    def __init__(self, client):
        self.client = client
        self.ws = None
        self.token = None
        self.joints: list[str] = []
        self.roms: dict[str, list[float]] = {}
        self._pump_stop = threading.Event()
        self._pump_thread = None

    def start_session(self, source="synthetic", config=None):
        response = self.client.post("/api/teleop/start", json={
            "source": source, "mode": "external", "config": config or {}})
        assert response.status_code == 200, response.text
        body = response.json()
        self.token = body["token"]
        return body

    def connect(self, token=None, proto=1, side="right", source="synthetic"):
        # NOTE: the session MUST be __exit__-ed (not merely .close()-d):
        # WebSocketTestSession._run sleeps forever after the app returns until
        # __exit__ cancels it, and an unfinished portal task deadlocks
        # TestClient.__exit__.
        self.ws = self.client.websocket_connect("/ws/teleop")
        self.ws.__enter__()
        self.ws.send_json({"type": "hello", "data": {
            "token": self.token if token is None else token,
            "proto": proto, "source": source,
            "hand": {"model_name": "mock-test", "side": side},
            "pid": 4242,
        }})
        ok = self.ws.receive_json()
        assert ok["type"] == "hello_ok", ok
        self.joints = ok["data"]["joints"]
        self.roms = ok["data"]["roms"]
        return ok["data"]

    def send_targets(self, angles):
        self.ws.send_json({"type": "targets", "data": {"angles": angles}})

    def send_status(self, **data):
        self.ws.send_json({"type": "status", "data": data})

    def mid_pose(self, offset_fraction=0.25):
        """A constant pose offset from ROM midpoints — far from the mock's
        boot pose, so ramping is observable."""
        pose = {}
        for joint in self.joints:
            lo, hi = self.roms[joint]
            span = hi - lo
            pose[joint] = (lo + hi) / 2.0 + offset_fraction * span / 2.0
        return pose

    def start_pump(self, pose=None, rate_hz=30.0):
        pose = pose or self.mid_pose()
        self._pump_stop.clear()

        def run():
            period = 1.0 / rate_hz
            while not self._pump_stop.is_set():
                try:
                    self.send_targets(pose)
                except Exception:
                    return
                time.sleep(period)

        self._pump_thread = threading.Thread(target=run, daemon=True)
        self._pump_thread.start()
        return pose

    def stop_pump(self):
        self._pump_stop.set()
        if self._pump_thread is not None:
            self._pump_thread.join(timeout=2.0)

    def disconnect(self):
        if self.ws is not None:
            try:
                self.ws.__exit__(None, None, None)
            except Exception:
                pass
            self.ws = None

    def close(self):
        self.stop_pump()
        self.disconnect()


@pytest.fixture()
def child(client):
    synthetic = SyntheticChild(client)
    yield synthetic
    synthetic.close()
    client.post("/api/teleop/stop")


def _enable_torque(client):
    response = client.post("/api/torque/enable")
    assert response.status_code == 200, response.text
    return response.json()["seed"]


def _engaged_session(client, child, ramp_s=0.0):
    """start external + connect + pump + torque + engage."""
    child.start_session()
    child.connect()
    pose = child.start_pump()
    _enable_torque(client)
    assert _wait_for(lambda: _teleop_state(client)["stats"]["target_hz"])
    response = client.post("/api/teleop/engage", json={"ramp_s": ramp_s})
    assert response.status_code == 200, response.text
    return pose


# ----- handshake / protocol ---------------------------------------------------------


def test_start_external_returns_token_and_hello_upgrades_to_preview(client, child):
    body = child.start_session()
    assert body["token"]
    assert body["session"]["state"] == "starting"
    assert body["session"]["mode"] == "external"

    child.connect()
    state = _teleop_state(client)
    assert state["state"] == "preview"
    assert state["source"] == "synthetic"
    assert state["child"]["connected"] is True
    assert state["child"]["pid"] == 4242


def _expect_hello_reject(client, hello_data, expected_code):
    with client.websocket_connect("/ws/teleop") as ws:
        ws.send_json({"type": "hello", "data": hello_data})
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
        assert excinfo.value.code == expected_code


def test_hello_rejects(client, child):
    child.start_session()

    _expect_hello_reject(client, {"token": "nope", "proto": 1,
                                  "source": "synthetic",
                                  "hand": {"side": "right"}}, 4001)
    assert _teleop_state(client)["state"] == "starting"   # session unharmed

    _expect_hello_reject(client, {"token": child.token, "proto": 1,
                                  "source": "synthetic",
                                  "hand": {"side": "left"}}, 4003)
    assert _teleop_state(client)["state"] == "starting"

    # good hello still works afterwards
    child.connect()
    assert _teleop_state(client)["state"] == "preview"


def test_start_conflicts_while_active(client, child):
    child.start_session()
    response = client.post("/api/teleop/start",
                           json={"source": "synthetic", "mode": "external"})
    assert response.status_code == 409

    assert client.post("/api/teleop/stop").json()["stopped"] is True
    assert _teleop_state(client)["state"] == "idle"
    # stop is idempotent
    assert client.post("/api/teleop/stop").json()["stopped"] is False


def test_unknown_source_400(client):
    response = client.post("/api/teleop/start",
                           json={"source": "telepathy", "mode": "external"})
    assert response.status_code == 400


# ----- preview: targets topic + clamping ----------------------------------------------


def test_preview_targets_published_and_clamped_not_forwarded(client, child):
    child.start_session()
    child.connect()

    # A joint that is NOT wrist — wrist is used below as the NaN victim.
    joint = next(j for j in child.joints if j != "wrist")
    lo, hi = child.roms[joint]
    child.send_targets({joint: hi + 1000.0, "not_a_joint": 1.0,
                        "wrist": float("nan")})

    payload = _wait_for(lambda: _hub_payload(client, T.TELEOP_TARGETS))
    assert payload["angles"][joint] == pytest.approx(hi)
    assert "not_a_joint" not in payload["angles"]
    assert "wrist" not in payload["angles"] or math.isfinite(
        payload["angles"]["wrist"])

    # preview never touches the command channel
    assert _hub_payload(client, T.JOINTS_TARGET) is None
    assert _control(client)["control_source"] == "manual"


def test_status_and_log_frames(client, child):
    child.start_session()
    child.connect()
    child.send_status(ingress_fps=29.5, tracking=True, retarget_ms=7.5,
                      calibrating={"done": False, "frames": 12, "needed": 30})
    assert _wait_for(
        lambda: _teleop_state(client)["stats"].get("ingress_fps") == 29.5)
    assert _teleop_state(client)["calibrating"]["frames"] == 12

    child.ws.send_json({"type": "log", "data": {"level": "info",
                                                "line": "hello from child"}})
    assert _wait_for(lambda: any(
        "hello from child" in entry["line"]
        for entry in client.get("/api/teleop/log").json()["lines"]))


# ----- engage / arbiter -------------------------------------------------------------


def test_engage_requires_torque(client, child):
    child.start_session()
    child.connect()
    child.send_targets(child.mid_pose())
    response = client.post("/api/teleop/engage", json={})
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


def test_engage_without_tracking_arms_then_ramps_on_first_frame(client, child):
    """The operator's hand is on the mouse, not in frame, when they click
    Engage: engaging must work anyway (hand holds), and the first arriving
    frames ramp in from the current pose."""
    child.start_session()
    child.connect()
    _enable_torque(client)

    response = client.post("/api/teleop/engage", json={"ramp_s": 0.2})
    assert response.status_code == 200
    assert response.json()["session"]["state"] == "engaged"

    # no targets yet -> watchdog flags tracking lost, hand just holds
    assert _wait_for(
        lambda: _teleop_state(client)["tracking"] == "lost", timeout=2.0)
    assert _teleop_state(client)["state"] == "engaged"
    baseline = client.app_state.hub.latest(T.JOINTS_TARGET)
    baseline_seq = baseline[0] if baseline else 0

    # hand enters the frame -> targets flow -> commands reach the channel
    child.start_pump()
    assert _wait_for(
        lambda: (client.app_state.hub.latest(T.JOINTS_TARGET) or (0,))[0]
        > baseline_seq, timeout=3.0)
    assert _wait_for(
        lambda: _teleop_state(client)["tracking"] == "ok", timeout=2.0)
    assert _teleop_state(client)["state"] == "engaged"


def test_engage_locks_manual_control_until_disengage(client, child):
    _engaged_session(client, child)

    control = _control(client)
    assert control["control_source"] == "teleop"
    assert "synthetic" in control["control_owner"]

    # manual slider path 409s (REST) and errors (WS)
    response = client.post("/api/joints/target",
                           json={"angles": {child.joints[0]: 0.0}})
    assert response.status_code == 409
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "cmd.joints.target",
                      "data": {"angles": {child.joints[0]: 0.0}}})
        reply = ws.receive_json()
        # first frames may be status/control snapshots; hunt for the error
        for _ in range(10):
            if reply["type"] == "error":
                break
            reply = ws.receive_json()
        assert reply["type"] == "error"

    # engaged targets flow through to the command channel
    assert _wait_for(lambda: _hub_payload(client, T.JOINTS_TARGET))

    response = client.post("/api/teleop/disengage")
    assert response.status_code == 200
    assert _wait_for(lambda: _control(client)["control_source"] == "manual")
    assert _teleop_state(client)["state"] == "preview"

    # manual control restored
    response = client.post("/api/joints/target",
                           json={"angles": {child.joints[0]: 0.0}})
    assert response.status_code == 200


def test_engage_ramps_from_current_pose(client, child):
    child.start_session()
    child.connect()
    seed = _enable_torque(client)
    pose = child.start_pump()
    assert _wait_for(lambda: _teleop_state(client)["stats"]["target_hz"])

    response = client.post("/api/teleop/engage", json={"ramp_s": 1.0})
    assert response.status_code == 200
    assert response.json()["session"]["ramping"] is True

    joint = child.joints[0]
    first = _wait_for(lambda: _hub_payload(client, T.JOINTS_TARGET))
    # Early in the ramp the command sits near the seed pose, not the target.
    start_value = seed.get(joint, 0.0)
    assert abs(first["angles"][joint] - start_value) < \
        abs(pose[joint] - start_value)

    # After the ramp: raw teleop target flows through unchanged.
    assert _wait_for(
        lambda: not _teleop_state(client)["ramping"], timeout=3.0)
    assert _wait_for(
        lambda: (_hub_payload(client, T.JOINTS_TARGET)["angles"].get(joint)
                 == pytest.approx(pose[joint], abs=1e-6)),
        timeout=2.0)


def test_operation_start_blocked_while_engaged(client, child):
    _engaged_session(client, child)
    response = client.post("/api/operation/test.fast/start", json={})
    assert response.status_code == 409
    assert "teleop" in response.json()["detail"]


def test_engage_blocked_while_operation_owns_control(client, child):
    child.start_session()
    child.connect()
    child.start_pump()
    _enable_torque(client)
    assert _wait_for(lambda: _teleop_state(client)["stats"]["target_hz"])

    assert client.post("/api/operation/test.hold/start").status_code == 200
    assert _wait_for(
        lambda: _control(client)["control_source"] == "operation")
    response = client.post("/api/teleop/engage", json={})
    assert response.status_code == 409

    client.post("/api/operation/stop")
    assert _wait_for(lambda: _control(client)["control_source"] == "manual")


# ----- watchdog ----------------------------------------------------------------------


def test_tracking_loss_holds_then_auto_disengages(client, child):
    _engaged_session(client, child)

    child.stop_pump()
    # hold_after_ms=100 -> tracking flips to lost
    assert _wait_for(
        lambda: _teleop_state(client)["tracking"] == "lost", timeout=2.0)
    assert _teleop_state(client)["state"] == "engaged"   # holding, not dropped

    # disengage_after_s=0.6 -> auto-disengage back to preview, LOUDLY
    assert _wait_for(
        lambda: _teleop_state(client)["state"] == "preview", timeout=3.0)
    assert _control(client)["control_source"] == "manual"
    assert "auto-disengaged" in (_teleop_state(client)["notice"] or "")
    assert "tracking lost" in _teleop_state(client)["notice"]


def test_torque_drop_auto_disengages(client, child):
    _engaged_session(client, child)
    client.post("/api/torque/disable")
    assert _wait_for(
        lambda: _teleop_state(client)["state"] == "preview", timeout=2.0)
    assert _control(client)["control_source"] == "manual"


def test_child_link_loss_fails_session(client, child):
    child.start_session()
    child.connect()
    child.disconnect()
    assert _wait_for(lambda: _teleop_state(client)["state"] == "error",
                     timeout=2.0)
    assert "link lost" in _teleop_state(client)["error"]

    # sticky error clears on the next start
    child.start_session()
    assert _teleop_state(client)["state"] == "starting"


# ----- e-stop ------------------------------------------------------------------------


def test_estop_ends_teleop_session(client, child):
    _engaged_session(client, child)

    report = client.post("/api/estop").json()["report"]
    assert report["teleop_stopped"] is True
    assert report["torque_disabled"] is True
    assert _teleop_state(client)["state"] == "idle"
    assert _control(client)["control_source"] == "manual"


# ----- config ------------------------------------------------------------------------


def test_config_set_while_starting_arrives_in_hello_ok(client, child):
    """The browser can toggle e.g. the camera preview while the child is
    still starting — the accumulated config must ride along in hello_ok
    (a plain config message would be lost: no link yet)."""
    child.start_session()
    response = client.post("/api/teleop/config",
                           json={"config": {"preview": True,
                                            "orientation_gate": False}})
    assert response.status_code == 200

    ack = child.connect()
    assert ack["config"]["preview"] is True
    assert ack["config"]["orientation_gate"] is False


def test_config_roundtrip_reaches_child(client, child):
    child.start_session()
    child.connect()
    response = client.post("/api/teleop/config",
                           json={"config": {"manual_wrist_deg": 12.5,
                                            "bogus_key": 1}})
    assert response.status_code == 200
    assert response.json()["config"]["manual_wrist_deg"] == 12.5
    assert "bogus_key" not in response.json()["config"]

    message = child.ws.receive_json()
    assert message["type"] == "config"
    assert message["data"]["manual_wrist_deg"] == 12.5

    response = client.post("/api/teleop/config", json={"config": {"nope": 1}})
    assert response.status_code == 400


# ----- WS snapshot replay --------------------------------------------------------------


def test_ws_replays_teleop_state_on_subscribe(client, child):
    child.start_session()
    child.connect()
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe",
                      "data": {"topics": [T.TELEOP_STATE]}})
        for _ in range(10):
            message = ws.receive_json()
            if message["type"] == T.TELEOP_STATE:
                break
        assert message["type"] == T.TELEOP_STATE
        assert message["data"]["state"] == "preview"


# ----- managed child runner --------------------------------------------------------------


def test_managed_spawn_captures_log_and_reports_exit(tmp_path):
    fake_child = tmp_path / "fake_child.py"
    fake_child.write_text(
        "import sys, time\n"
        "print('fake child started', flush=True)\n"
        "time.sleep(0.3)\n"
        "sys.exit(3)\n"
    )
    config_path = materialize_mock_model()
    settings = UiSettings(
        config_path=config_path, mock=True, open_browser=False,
        teleop_cmd=f"{sys.executable} {fake_child}",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.app_state = app.state
        assert _wait_for(
            lambda: client.get("/api/status").json()["state"] == "connected")

        response = client.post("/api/teleop/start",
                               json={"source": "synthetic"})
        assert response.status_code == 200, response.text
        assert response.json()["session"]["state"] == "starting"

        assert _wait_for(
            lambda: client.get("/api/teleop/state").json()["session"]["state"]
            == "error", timeout=5.0)
        state = client.get("/api/teleop/state").json()["session"]
        assert "exited (code 3)" in state["error"]
        lines = [entry["line"]
                 for entry in client.get("/api/teleop/log").json()["lines"]]
        assert any("fake child started" in line for line in lines)


def test_managed_spawn_unavailable_503(tmp_path):
    config_path = materialize_mock_model()
    settings = UiSettings(
        config_path=config_path, mock=True, open_browser=False,
        teleop_dir=str(tmp_path / "does-not-exist"),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert _wait_for(
            lambda: client.get("/api/status").json()["state"] == "connected")
        response = client.post("/api/teleop/start",
                               json={"source": "mediapipe"})
        assert response.status_code == 503


def test_sources_listing(client):
    body = client.get("/api/teleop/sources").json()
    assert set(body["sources"]) == {"mediapipe", "synthetic", "manus", "avp"}
    assert "runner" in body
    assert body["cameras"] is None   # never scanned in this app instance


def test_camera_scan_via_fake_probe(tmp_path):
    fake_probe = tmp_path / "fake_probe.py"
    fake_probe.write_text(
        "import sys\n"
        "print('noise that is not json')\n"
        "print('[{\"index\": 0, \"width\": 1280, \"height\": 720}, "
        "{\"index\": 1, \"width\": 640, \"height\": 480}]')\n"
    )
    config_path = materialize_mock_model()
    settings = UiSettings(
        config_path=config_path, mock=True, open_browser=False,
        teleop_cmd=f"{sys.executable} {fake_probe}",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert _wait_for(
            lambda: client.get("/api/status").json()["state"] == "connected")

        response = client.post("/api/teleop/cameras/scan")
        assert response.status_code == 200, response.text
        cameras = response.json()["cameras"]
        # probed cameras always listed as available; the host may add extra
        # OS-known-but-unopenable ones (e.g. a sleeping Continuity Camera)
        probed = [c for c in cameras if c["available"]]
        assert [c["index"] for c in probed] == [0, 1]
        # names come from the host (macOS system_profiler; may be empty
        # elsewhere) and the default is picked from the openable set
        assert response.json()["default_camera_index"] in (0, 1)

        # cached into the sources listing
        body = client.get("/api/teleop/sources").json()
        assert [c["index"] for c in body["cameras"]] == [0, 1]

        # scanning is refused while a session is live (it would steal the
        # camera)
        client.post("/api/teleop/start",
                    json={"source": "synthetic", "mode": "external"})
        assert client.post("/api/teleop/cameras/scan").status_code == 409
        client.post("/api/teleop/stop")

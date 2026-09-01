"""Teleop subsystem tests: ingress protocol, arbiter integration, ramp,
watchdog, e-stop, and the managed-child runner.

A synthetic client drives the real ``/ws/teleop`` wire protocol over the
TestClient (external mode), so CI needs no orca_teleop environment.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

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


# ----- preview: targets topic + clamping ----------------------------------------------


# ----- engage / arbiter -------------------------------------------------------------


def test_engage_requires_torque(client, child):
    child.start_session()
    child.connect()
    child.send_targets(child.mid_pose())
    response = client.post("/api/teleop/engage", json={})
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


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


# ----- e-stop ------------------------------------------------------------------------


def test_estop_ends_teleop_session(client, child):
    _engaged_session(client, child)

    report = client.post("/api/estop").json()["report"]
    assert report["teleop_stopped"] is True
    assert report["torque_disabled"] is True
    assert _teleop_state(client)["state"] == "idle"
    assert _control(client)["control_source"] == "manual"


# ----- config ------------------------------------------------------------------------


# ----- WS snapshot replay --------------------------------------------------------------


# ----- managed child runner --------------------------------------------------------------


# ----- orca_teleop checkout: availability probe + install ---------------------------------


def _fake_bin(tmp_path, name, body):
    """An executable stand-in for git/uv, so the installer's real Popen +
    output pump + exit-code handling is what gets exercised."""
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)

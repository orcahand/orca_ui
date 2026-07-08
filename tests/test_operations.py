"""Operation manager lifecycle, control-source arbiter, and e-stop tests.

Uses dummy operations registered into the real manager over the mock hand,
so the REST/WS contracts are exercised exactly as production ops will.
"""

import json
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
        for i in range(3):
            ctx.log(f"line {i}")
            ctx.set_progress((i + 1) / 3, detail=f"step {i}")
        return {"count": 3}


class HoldOp(Operation):
    """Owns the joint-target channel until stopped."""

    kind = "test.hold"
    control_source = ControlSource.OPERATION

    def run(self, ctx):
        ctx.set_phase("holding")
        while True:
            ctx.sleep(0.05)


class InputOp(Operation):
    kind = "test.input"

    def run(self, ctx):
        answer = ctx.wait_input("continue?", ["yes", "no"])
        return {"answer": answer}


@pytest.fixture()
def client():
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True, open_browser=False)
    app = create_app(settings)
    for op_cls in (FastOp, HoldOp, InputOp):
        app.state.operations.register(op_cls)
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _wait_state(client, state, timeout=5.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def test_operation_lifecycle_and_log(client):
    started = client.post("/api/operation/test.fast/start", json={})
    assert started.status_code == 200
    snapshot = _wait_state(client, "done")
    assert snapshot["kind"] == "test.fast"
    assert snapshot["result"] == {"count": 3}
    assert snapshot["progress"] == 1.0

    log = client.get("/api/operation/log").json()
    assert [entry["line"] for entry in log["lines"]] == [
        "line 0", "line 1", "line 2"]
    assert log["next_seq"] == 3
    assert log["run_id"] == snapshot["run_id"]


def test_second_start_conflicts(client):
    assert client.post("/api/operation/test.hold/start").status_code == 200
    response = client.post("/api/operation/test.fast/start")
    assert response.status_code == 409
    assert "test.hold" in response.json()["detail"]
    client.post("/api/operation/stop")
    _wait_state(client, "done")


def test_unknown_kind_404(client):
    assert client.post("/api/operation/nope/start").status_code == 404


def test_stop_reports_stopped(client):
    client.post("/api/operation/test.hold/start")
    _wait_for(lambda: (_operation(client) or {}).get("phase") == "holding")
    response = client.post("/api/operation/stop")
    assert response.json()["stopped"] is True
    snapshot = _wait_state(client, "done")
    assert snapshot["detail"] == "stopped"
    # A stop with nothing running is a no-op, not an error.
    assert client.post("/api/operation/stop").json()["stopped"] is False


def test_awaiting_input_roundtrip(client):
    # Input with nothing awaiting is a 409.
    assert client.post("/api/operation/input",
                       json={"value": "yes"}).status_code == 409

    client.post("/api/operation/test.input/start")
    snapshot = _wait_state(client, "awaiting_input")
    assert snapshot["awaiting"] == {"prompt": "continue?",
                                    "options": ["yes", "no"]}
    assert client.post("/api/operation/input",
                       json={"value": "yes"}).status_code == 200
    snapshot = _wait_state(client, "done")
    assert snapshot["result"] == {"answer": "yes"}


def test_control_source_arbiter(client):
    service = client.app_state.service
    hub = client.app_state.hub

    assert client.post("/api/torque/enable").status_code == 200
    client.post("/api/operation/test.hold/start")
    _wait_for(lambda: (_operation(client) or {}).get("phase") == "holding")

    # Manual writes are rejected, naming the owner.
    response = client.post("/api/joints/target",
                           json={"angles": {"index_mcp": 20.0}})
    assert response.status_code == 409
    assert "test.hold" in response.json()["detail"]

    # Torque enable / neutral are gated too (a second tab must not fight
    # a running operation).
    assert client.post("/api/torque/enable").status_code == 409
    assert client.post("/api/joints/neutral").status_code == 409
    # Disabling torque stays allowed (safety).
    assert client.post("/api/torque/disable").status_code == 200
    assert client.post("/api/torque/enable").status_code == 409
    # Re-enable via service internals for the operation-write check below.
    session = service.session
    session.hand.enable_torque()
    service.supervisor.set_torque_flag(True)

    # The owner's own writes pass validation AND publish the target echo.
    before = (hub.latest(T.JOINTS_TARGET) or (0,))[0]
    service.set_targets({"index_mcp": 21.5}, source=ControlSource.OPERATION)
    entry = hub.latest(T.JOINTS_TARGET)
    assert entry[0] > before
    assert entry[2]["angles"]["index_mcp"] == 21.5

    # control.state carries the owner while held...
    assert service.control_state()["control_source"] == "operation"
    assert service.control_state()["control_owner"] == "test.hold"

    client.post("/api/operation/stop")
    _wait_state(client, "done")
    # ...and reverts to manual after release.
    assert service.control_state()["control_source"] == "manual"
    assert client.post("/api/joints/target",
                       json={"angles": {"index_mcp": 20.0}}).status_code == 200


def test_estop_stops_operation_and_torque(client):
    assert client.post("/api/torque/enable").status_code == 200
    client.post("/api/operation/test.hold/start")
    _wait_for(lambda: (_operation(client) or {}).get("phase") == "holding")

    response = client.post("/api/estop")
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["operation_stopped"] is True
    assert report["torque_disabled"] is True
    assert report["sweeper_stopped"] is True

    snapshot = _wait_state(client, "error")
    assert snapshot["detail"] == "stopped (e-stop)"
    assert client.get("/api/status").json()["torque_enabled"] is False

    # E-stop with nothing running is still a clean 200.
    report = client.post("/api/estop").json()["report"]
    assert report["operation_stopped"] is False


def test_ws_replays_operation_snapshots(client):
    client.post("/api/operation/test.fast/start")
    _wait_state(client, "done")

    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({
            "type": "subscribe",
            "data": {"topics": ["operation.state", "operation.log"]},
        }))
        got = {}
        deadline = time.time() + 5.0
        while time.time() < deadline and len(got) < 2:
            message = json.loads(ws.receive_text())
            if message["type"] in ("operation.state", "operation.log"):
                got[message["type"]] = message["data"]
        assert got["operation.state"]["state"] == "done"
        assert got["operation.state"]["kind"] == "test.fast"
        # Cumulative log payload: a fresh subscriber gets the whole buffer.
        assert [e["line"] for e in got["operation.log"]["lines"]] == [
            "line 0", "line 1", "line 2"]

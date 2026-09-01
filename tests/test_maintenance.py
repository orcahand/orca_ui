"""Maintenance lease FSM + simulated calibrate/tension operation tests."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.operations import Operation
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.05}


def _wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


class FailingMaintenanceOp(Operation):
    """Takes the real lease, then dies — the lease must still be released."""

    kind = "test.fail_maint"

    def run(self, ctx):
        ctx.service.supervisor.enter_maintenance(self.kind)
        try:
            raise RuntimeError("simulated hardware failure")
        finally:
            ctx.service.supervisor.exit_maintenance()


@pytest.fixture()
def client():
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True, open_browser=False)
    app = create_app(settings)
    app.state.operations.register(FailingMaintenanceOp)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _state(client):
    return client.get("/api/status").json()["state"]


def _wait_op_state(client, state, timeout=10.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def _wait_reconnected(client, timeout=15.0):
    assert _wait_for(lambda: _state(client) == "connected", timeout=timeout), \
        f"never reconnected: {_state(client)}"


def test_simulated_calibrate_full_run(client):
    response = client.post("/api/operation/calibrate/start",
                           json={"params": FAST})
    assert response.status_code == 200

    # The lease closes the session: status flips to maintenance and stays
    # there while the op runs (health checks and reconnect suspended).
    assert _wait_for(lambda: _state(client) == "maintenance")
    assert (_operation(client) or {}).get("kind") == "calibrate"
    # No session while in maintenance: manual control is 503.
    assert client.post("/api/joints/target",
                       json={"angles": {"index_mcp": 5.0}}).status_code == 503

    snapshot = _wait_op_state(client, "done", timeout=20.0)
    assert snapshot["progress"] == 1.0
    assert snapshot["result"]["calibrated"] is True
    assert snapshot["result"]["steps_done"] > 10
    assert "index_mcp" in snapshot["result"]["joints_calibrated"]

    log = client.get("/api/operation/log").json()
    assert any("calibration complete" in e["line"] for e in log["lines"])
    _wait_reconnected(client)


def test_calibrate_unknown_joint_rejected(client):
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {"joints": ["not_a_joint"]}})
    assert response.status_code == 400
    assert "not_a_joint" in response.json()["detail"]
    assert _state(client) == "connected"   # nothing was scheduled


def test_calibrate_current_override_bounds(client):
    # Below the 50 mA floor: the sweep would stall on friction.
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {"calibration_current": 20}})
    assert response.status_code == 400
    assert "50" in response.json()["detail"]
    # Above the configured max_current ceiling.
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {"calibration_current": 100000}})
    assert response.status_code == 400
    # Not a number.
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {"calibration_current": "lots"}})
    assert response.status_code == 400
    assert _state(client) == "connected"   # nothing was scheduled


def test_estop_during_tension_hold(client):
    client.post("/api/operation/tension/start", json={"params": FAST})
    _wait_op_state(client, "awaiting_input")

    response = client.post("/api/estop")
    assert response.status_code == 200
    assert response.json()["report"]["operation_stopped"] is True

    snapshot = _wait_op_state(client, "error")
    assert snapshot["detail"] == "stopped (e-stop)"
    _wait_reconnected(client)


def test_failed_maintenance_op_releases_lease(client):
    client.post("/api/operation/test.fail_maint/start")
    snapshot = _wait_op_state(client, "error")
    assert "simulated hardware failure" in snapshot["error"]
    _wait_reconnected(client)


def test_concurrent_maintenance_rejected(client):
    client.post("/api/operation/tension/start", json={"params": FAST})
    _wait_op_state(client, "awaiting_input")
    assert client.post("/api/operation/calibrate/start",
                       json={"params": FAST}).status_code == 409
    client.post("/api/operation/stop")
    _wait_op_state(client, "done")
    _wait_reconnected(client)


# ----- manual (hands-on) calibration -----------------------------------------


# ----- calibration alerts -----------------------------------------------------


class _Ctx:
    """Minimal OpContext: records what the run publishes."""

    def __init__(self):
        self.extra: dict = {}
        self.lines: list[str] = []

    def set_extra(self, extra):
        self.extra = extra

    def log(self, line):
        self.lines.append(line)

    def set_phase(self, *a, **k):
        pass

    def set_detail(self, *a, **k):
        pass

    def set_progress(self, *a, **k):
        pass

    def check_stop(self):
        pass


class _Hand:
    calibrated = True

    def __init__(self, tmp_path):
        class _Config:
            calibration_path = str(tmp_path / "calibration.yaml")
        self.config = _Config()


def _run_with_events(tmp_path, monkeypatch, events):
    """Drive run_calibrate over a canned event stream."""
    from orca_ui.hand.operations import calibrate as cal

    monkeypatch.setattr(
        cal.hand_ops, "calibrate",
        lambda hand, *, progress_callback, **kw: [
            progress_callback(e) for e in events])
    ctx = _Ctx()
    result = cal.run_calibrate(_Hand(tmp_path), None, ctx,
                               joints=None, force_wrist=False)
    return result, ctx


def test_a_motionless_sweep_becomes_an_error_alert(tmp_path, monkeypatch):
    """The step completes in milliseconds, so the log alone scrolls past it."""
    result, ctx = _run_with_events(tmp_path, monkeypatch, [
        {"event": "sweep_no_motion", "joint": "thumb_mcp", "motor": 15,
         "direction": "flex", "moved_deg": 0.04},
    ])

    problem = result["problems"][0]
    assert problem["kind"] == "no_motion"
    assert problem["severity"] == "error"
    assert problem["joint"] == "thumb_mcp"
    assert "did not move" in problem["headline"]
    assert problem["advice"]
    # Published live, not only in the final result.
    assert ctx.extra["problems"] == result["problems"]

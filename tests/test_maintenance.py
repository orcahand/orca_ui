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


def test_simulated_calibrate_subset(client):
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {**FAST, "joints": ["index_mcp"]}})
    assert response.status_code == 200
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"]["joints_calibrated"] == ["index_mcp"]
    assert snapshot["result"]["steps_done"] <= 2
    _wait_reconnected(client)


def test_calibrate_unknown_joint_rejected(client):
    response = client.post(
        "/api/operation/calibrate/start",
        json={"params": {"joints": ["not_a_joint"]}})
    assert response.status_code == 400
    assert "not_a_joint" in response.json()["detail"]
    assert _state(client) == "connected"   # nothing was scheduled


def test_simulated_tension_hold_release(client):
    client.post("/api/operation/tension/start", json={"params": FAST})
    snapshot = _wait_op_state(client, "awaiting_input")
    assert snapshot["phase"] == "holding"
    assert snapshot["awaiting"]["options"] == ["Release"]
    assert _state(client) == "maintenance"

    assert client.post("/api/operation/input",
                       json={"value": "Release"}).status_code == 200
    snapshot = _wait_op_state(client, "done")
    assert snapshot["result"] == {"released": True}
    assert snapshot["phase"] == "released"
    _wait_reconnected(client)


def test_estop_during_tension_hold(client):
    client.post("/api/operation/tension/start", json={"params": FAST})
    _wait_op_state(client, "awaiting_input")

    response = client.post("/api/estop")
    assert response.status_code == 200
    assert response.json()["report"]["operation_stopped"] is True

    snapshot = _wait_op_state(client, "error")
    assert snapshot["detail"] == "stopped (e-stop)"
    _wait_reconnected(client)


def test_stop_during_calibrate(client):
    client.post("/api/operation/calibrate/start",
                json={"params": {"step_duration_s": 0.3}})
    assert _wait_for(
        lambda: (_operation(client) or {}).get("phase") == "calibrating")
    client.post("/api/operation/stop")
    snapshot = _wait_op_state(client, "done")
    assert snapshot["detail"] == "stopped"
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


# --- the optional winding pass -------------------------------------------
# Tensioning normally drives every tendon to its stall in both directions
# before holding. On a hand whose spools are already close that is motion for
# nothing, so the pass is skippable and the motors just hold where they are.


def _log_text(client) -> str:
    return " ".join(
        entry["line"] for entry in client.get("/api/operation/log").json()["lines"]
    )


def test_tension_winds_by_default(client):
    client.post("/api/operation/tension/start", json={"params": FAST})
    snapshot = _wait_op_state(client, "awaiting_input")

    assert snapshot["params"]["move_motors"] is True
    assert "winding" in _log_text(client)

    client.post("/api/operation/input", json={"value": "Release"})
    _wait_op_state(client, "done")
    _wait_reconnected(client)


def test_tension_can_hold_without_winding(client):
    """The motors reach the hold without a winding or ramp phase: nothing is
    driven anywhere, which is the whole point of asking for it."""
    client.post("/api/operation/tension/start",
                json={"params": {**FAST, "move_motors": False}})
    snapshot = _wait_op_state(client, "awaiting_input")

    assert snapshot["phase"] == "holding"
    assert snapshot["params"]["move_motors"] is False
    assert "winding" not in _log_text(client)
    assert "ramping" not in _log_text(client)

    # Still a real hold that has to be released, and still ends torque-off.
    assert snapshot["awaiting"]["options"] == ["Release"]
    client.post("/api/operation/input", json={"value": "Release"})
    done = _wait_op_state(client, "done")
    assert done["phase"] == "released"
    _wait_reconnected(client)


def test_the_hold_is_reported_so_a_reload_knows_which_run_it_is(client):
    """The card reads the run's own params rather than its local tickbox, so a
    browser that reloads mid-hold still describes what actually happened."""
    client.post("/api/operation/tension/start",
                json={"params": {**FAST, "move_motors": False}})
    _wait_op_state(client, "awaiting_input")

    assert _operation(client)["params"]["move_motors"] is False

    client.post("/api/operation/input", json={"value": "Release"})
    _wait_op_state(client, "done")
    _wait_reconnected(client)

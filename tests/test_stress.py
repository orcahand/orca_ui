"""Cable-integrity stress test operation, over the mock hand."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=15.0, interval=0.02):
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


def _wait_op_state(client, state, timeout=30.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def _start(client, **params):
    return client.post("/api/operation/stress_test/start",
                       json={"params": params})


def _rom(client, joint):
    joints = client.get("/api/hand/info").json()["joints"]
    return next(j["rom"] for j in joints if j["id"] == joint)


# ----- validation -----------------------------------------------------------


def test_needs_torque(client):
    response = _start(client, joints=["index_mcp"], cycles=1)
    assert response.status_code == 409
    assert "torque" in response.json()["detail"]


def test_rejects_an_empty_or_unknown_joint_list(client):
    assert client.post("/api/torque/enable").status_code == 200
    assert _start(client, joints=[], cycles=1).status_code == 400
    response = _start(client, joints=["nope"], cycles=1)
    assert response.status_code == 400
    assert "unknown joints" in response.json()["detail"]


def test_rejects_a_margin_that_leaves_no_travel(client):
    assert client.post("/api/torque/enable").status_code == 200
    response = _start(client, joints=["index_mcp"], cycles=1, margin_deg=15.0)
    # The mock index_mcp spans well over 30°, so 15° a side still leaves
    # travel — the check is that an absurd margin is refused, not accepted.
    if response.status_code == 200:
        client.post("/api/operation/stop")
        _wait_op_state(client, "done")
    response = _start(client, joints=["index_mcp"], cycles=1, margin_deg=99.0)
    assert response.status_code == 400
    assert "margin_deg" in response.json()["detail"]


def test_rejects_out_of_range_cycles_and_speed(client):
    assert client.post("/api/torque/enable").status_code == 200
    assert _start(client, joints=["index_mcp"], cycles=0).status_code == 400
    assert _start(client, joints=["index_mcp"], cycles=5000).status_code == 400
    response = _start(client, joints=["index_mcp"], cycles=1, speed=7.0)
    assert response.status_code == 400
    assert "speed" in response.json()["detail"]


# ----- running ---------------------------------------------------------------


def test_cycles_a_joint_end_to_end_and_reports_reach(client):
    assert client.post("/api/torque/enable").status_code == 200
    lo, hi = _rom(client, "index_mcp")

    assert _start(client, joints=["index_mcp"], cycles=2, speed=2.0,
                  hold_s=0.0).status_code == 200

    # The commanded target visits both ends of the ROM, not just one.
    service = client.app.state.service
    seen = set()

    def watch():
        target = service._targets.get("index_mcp")
        if target is None:
            return False
        if abs(target - hi) < 1.0:
            seen.add("hi")
        if abs(target - lo) < 1.0:
            seen.add("lo")
        return len(seen) == 2

    assert _wait_for(watch), f"targets never reached both ends: {seen}"

    snapshot = _wait_op_state(client, "done")
    result = snapshot["result"]
    assert result["cycles"] == 2
    assert result["joints"] == ["index_mcp"]
    assert result["measured"] is True

    row = result["report"][0]
    assert row["id"] == "index_mcp"
    assert row["target"] == [lo, hi]
    # The mock hand tracks its targets, so it gets most of the way there.
    assert row["span_deg"] > 0.5 * row["commanded_span_deg"]
    assert row["span_shortfall_deg"] is not None


def test_leaves_unpicked_joints_alone(client):
    """Only the picked joints are ever commanded — enabling torque seeds a
    target for every joint, and the run must not touch the rest of them."""
    assert client.post("/api/torque/enable").status_code == 200
    service = client.app.state.service
    before = dict(service._targets)
    assert len(before) > 1, "torque enable should seed every joint"

    assert _start(client, joints=["index_mcp"], cycles=1, speed=2.0,
                  hold_s=0.0).status_code == 200
    _wait_op_state(client, "done")

    after = dict(service._targets)
    assert after["index_mcp"] != before["index_mcp"]
    untouched = {j: v for j, v in after.items() if j != "index_mcp"}
    assert untouched == {j: v for j, v in before.items() if j != "index_mcp"}


def test_stop_ends_the_run_and_keeps_the_report(client):
    assert client.post("/api/torque/enable").status_code == 200
    assert _start(client, joints=["index_mcp", "middle_mcp"], loop=True,
                  speed=0.5).status_code == 200
    _wait_op_state(client, "running")
    # Let it get through at least the first extreme so there is something
    # measured to keep.
    assert _wait_for(
        lambda: ((_operation(client) or {}).get("extra") or {}).get("joints"))
    assert client.post("/api/operation/stop").json()["stopped"] is True

    snapshot = _wait_op_state(client, "done")
    assert snapshot["detail"] == "stopped"
    # The per-leg extra survives into the terminal snapshot — it is the
    # result the operator ran the test for.
    assert len(snapshot["extra"]["joints"]) == 2
    assert snapshot["extra"]["loop"] is True


def test_only_one_operation_at_a_time(client):
    assert client.post("/api/torque/enable").status_code == 200
    assert _start(client, joints=["index_mcp"], loop=True).status_code == 200
    _wait_op_state(client, "running")
    second = _start(client, joints=["ring_mcp"], cycles=1)
    assert second.status_code == 409
    client.post("/api/operation/stop")
    _wait_op_state(client, "done")

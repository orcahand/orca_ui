"""Motor testbench: the cycling operation's safety gates and the contract the
bench page reads, over a simulated two-motor bench."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.bench import materialize_bench_model
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


def _client(config_path, tmp_path, bench):
    settings = UiSettings(config_path=config_path, mock=True, bench=bench,
                          open_browser=False, library_dir=str(tmp_path))
    return TestClient(create_app(settings))


@pytest.fixture()
def bench(tmp_path):
    with _client(materialize_bench_model([1, 2], mock=True), tmp_path, True) as c:
        assert _wait_for(lambda: c.get("/api/status").json()["state"] == "connected")
        yield c


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _start(client, **params):
    return client.post("/api/operation/motor_cycle/start", json={"params": params})


def test_cycle_runs_in_motor_space_behind_the_torque_gate(bench):
    # Two motors, two different cycles, one run: they are not synchronized.
    motors = [{"id": 1, "from_deg": 0.0, "to_deg": 90.0, "cycles": 2,
               "speed_deg_s": 2000, "hold_s": 0.0},
              {"id": 2, "from_deg": 10.0, "to_deg": -80.0, "cycles": 1,
               "speed_deg_s": 500, "hold_s": 0.05, "mode": "step",
               "start_at": "to"}]

    # Nothing moves without torque: the gate is the operation's, not the UI's,
    # and it is per motor — holding one spool to wind the other is the
    # tensioning posture, and a released motor must not be cycled.
    assert _start(bench, motors=motors).status_code == 409
    assert bench.post("/api/motors/1/torque", json={"enabled": True}).status_code == 200
    assert bench.get("/api/status").json()["torque_enabled"] is True
    assert bench.get("/api/hand/info").json()["control"]["held_motors"] == [1]
    assert _start(bench, motors=motors).status_code == 409
    assert bench.post("/api/motors/2/torque", json={"enabled": True}).status_code == 200
    # What the page does on load: keep reading the shafts while torque is on.
    bench.post("/api/control/pose_source", json={"mode": "estimate"})
    # The bench is uncalibrated: a range any hand would refuse is fine here,
    # but one past the span cap is a typo, not a test.
    assert _start(bench, motors=[{"id": 1, "from_deg": 0, "to_deg": 5000,
                                  "cycles": 1}]).status_code == 400

    # Parts capped at 1 MB in service; here the cap is a few rows so the
    # run proves it rolls over without losing a row or a header.
    response = _start(bench, motors=motors, log=True, log_part_mb=0.002)
    assert response.status_code == 200, response.text
    # The CSV log is a switch the page flips mid-run through operation input.
    assert _wait_for(lambda: (_operation(bench).get("extra") or {}).get("log", {}).get("rows"))
    assert bench.post("/api/operation/input", json={"value": "log off"}).status_code == 200
    assert _wait_for(lambda: _operation(bench)["extra"]["log"]["on"] is False)
    assert bench.post("/api/operation/input", json={"value": "log on"}).status_code == 200
    assert _wait_for(
        lambda: (_operation(bench) or {}).get("state") == "done", timeout=30)

    # The page's live readouts, replayed from the hub the moment a client
    # subscribes: raw shaft state for every motor, calibrated or not, and
    # whether the PC sees a board at all.
    with bench.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "subscribe",
                                 "data": {"topics": ["motors.state",
                                                     "usb.presence"]}}))
        seen = {}
        for _ in range(40):
            message = json.loads(ws.receive_text())
            seen.setdefault(message["type"], message["data"])
            if {"motors.state", "usb.presence"} <= set(seen):
                break
    state = seen["motors.state"]
    assert set(state["positions"]) == {"1", "2"} and "currents" in state
    usb = seen["usb.presence"]
    assert usb["present"] is True and usb["devices"][0]["kind"] == "mock"

    result = _operation(bench)["result"]
    assert result["cycles"] == {"1": 2, "2": 1}
    assert len(result["log_files"]) > 1 and result["log_file"] == result["log_files"][-1]
    rows = []
    for name in result["log_files"]:
        log = bench.get(f"/api/bench/logs/{name}")
        assert log.status_code == 200
        header, *part = log.text.strip().splitlines()
        assert header.startswith("time,t_s,event,motor,id,cycle,")
        rows += part
    assert len(rows) == result["log_rows"]
    assert sum(1 for r in rows if ",cycle," in r) == 3
    assert bench.get("/api/bench/logs/config.yaml").status_code == 404
    by_id = {row["id"]: row for row in result["motors"]}
    assert by_id[1]["reached_to_deg"] == pytest.approx(90.0, abs=2.0)
    assert by_id[2]["reached_from_deg"] == pytest.approx(10.0, abs=2.0)
    assert by_id[1]["travel_deg"] == pytest.approx(4 * 90.0, abs=1.0)
    assert by_id[2]["travel_deg"] == pytest.approx(2 * 90.0, abs=1.0)
    # The run let go of the hardware: direct motor mode disarmed, control manual.
    control = bench.get("/api/hand/info").json()["control"]
    assert control["direct_motor_mode"] is False
    assert control["control_source"] == "manual"


def test_bus_scan_finds_motors_and_the_bench_adopts_them(bench):
    """The config guesses which motors are on the bus; the scan knows. Adopting
    its answer rewrites the bench config and reconnects on the new set."""
    response = bench.post("/api/operation/bus_scan/start",
                          json={"params": {"simulate_ids": [1, 2, 5]}})
    assert response.status_code == 200, response.text
    assert _wait_for(lambda: (_operation(bench) or {}).get("state") == "done")
    result = _operation(bench)["result"]
    assert result["motor_ids"] == [1, 2, 5]
    assert result["unconfigured"] == [5] and result["missing"] == []
    assert {m["id"] for m in result["motors"]} == {1, 2, 5}

    # The scan held the bus under the maintenance lease; the ladder is back.
    assert _wait_for(lambda: bench.get("/api/status").json()["state"] == "connected")
    # Numbers are the operator's, ids are the bus's: id 5 becomes motor 1,
    # id 2 stays motor 2, id 1 is left off the bench.
    response = bench.post("/api/bench/motors", json={"motors": [
        {"id": 5, "number": 1}, {"id": 2, "number": 2}]})
    assert response.status_code == 200, response.text
    assert _wait_for(lambda: [(j["id"], j["motor_id"]) for j in
                              bench.get("/api/hand/info").json()["joints"]]
                     == [("motor_1", 5), ("motor_2", 2)])
    assert bench.post("/api/bench/motors", json={"motors": [
        {"id": 5, "number": 1}, {"id": 2, "number": 1}]}).status_code == 400
    # The config is in force at once; the session on it follows the ladder.
    assert _wait_for(lambda: bench.get("/api/status").json()["state"] == "connected")


def test_calibrated_motor_cannot_be_cycled_past_its_travel(tmp_path):
    """Cycling a hand's motor from the bench page must stay inside the travel
    calibration measured — past it is the hardstop and the tendon."""
    with _client(materialize_mock_model(), tmp_path, False) as hand:
        assert _wait_for(lambda: hand.get("/api/status").json()["state"] == "connected")
        hand.post("/api/torque/enable")
        motor = hand.get("/api/hand/info").json()["joints"][1]["motor_id"]
        response = _start(hand, motors=[{"id": motor, "from_deg": -400,
                                         "to_deg": 400, "cycles": 1}])
        assert response.status_code == 400
        assert "calibrated" in response.json()["detail"]
        # A hand's motor list is the hand's: the bench page may not rewrite it.
        assert hand.post("/api/bench/motors", json={"motor_ids": [1]}).status_code == 409

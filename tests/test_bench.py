"""Motor testbench: the cycling operation's safety gates and the contract the
bench page reads, over a simulated two-motor bench."""

import json
import math
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


def test_thermal_test_drives_locked_motors_behind_its_gates(bench):
    """The thermal bench writes Goal Current itself: nothing without torque,
    nothing above the ceiling, and the ceiling is back on when it ends."""
    start = lambda **p: bench.post("/api/operation/motor_thermal/start",  # noqa: E731
                                   json={"params": p})
    # Nothing is driven without torque; the gate is per motor.
    assert start(motors=[1, 2]).status_code == 409
    assert bench.post("/api/motors/1/torque", json={"enabled": True}).status_code == 200
    assert start(motors=[1, 2]).status_code == 409
    assert bench.post("/api/motors/2/torque", json={"enabled": True}).status_code == 200
    # |offset| + amplitude must fit under the console's current ceiling.
    ceiling = bench.get("/api/hand/info").json()["control"]["max_current"]
    assert start(motors=[1, 2], amplitude_ma=ceiling, offset_ma=1).status_code == 400
    assert start(motors=[1, 2], temp_limit_c=500).status_code == 400
    # A coupled pair is one unit: both in the test or neither.
    assert start(motors=[1], pairs=[[1, 2]]).status_code == 400

    response = start(motors=[{"id": 1}, {"id": 2, "invert": True}], pairs=[[1, 2]],
                     amplitude_ma=100, offset_ma=20, frequency_hz=2.0, duration_s=1.0,
                     cooldown_s=0.5, log=True, log_hz=10)
    assert response.status_code == 200, response.text
    assert bench.get("/api/hand/info").json()["control"]["direct_motor_mode"] is True
    extra = _wait_for(lambda: (_operation(bench).get("extra") or {}).get("live", {}).get("goal_ma")
                      and _operation(bench)["extra"])
    # What the page reads: a report per motor and the live goal/actual pair.
    for key in ("phase", "progress", "driving", "temp_limit_c", "max_temp_c",
                "live", "motors", "history_points", "log"):
        assert key in extra, key
    assert {m["id"] for m in extra["motors"]} == {1, 2}
    assert extra["motors"][1]["invert"] is True
    assert extra["motors"][0]["partner"] == 2 and extra["pairs"] == [[1, 2]]
    # The mock reads back what was written: the goal current is the current.
    assert 0 <= extra["live"]["goal_ma"]["1"] <= 120

    final = _wait_for(lambda: _operation(bench)["state"] in ("done", "error")
                      and _operation(bench), timeout=20)
    assert final["state"] == "done", final
    report = {m["id"]: m for m in final["result"]["motors"]}
    assert report[1]["state"] == "done" and report[1]["temp_c"] is not None
    assert final["result"]["log_rows"] > 0
    history = bench.get("/api/thermal/history").json()
    assert history["run_id"] == final["run_id"] and set(history["temps"]) == {"1", "2"}
    # The page's pairing is the bench's, kept beside its config, not the browser's.
    saved = bench.put("/api/thermal/setup", json={"pairs": [{"a": 1, "b": 2, "opposed": False}]})
    assert saved.status_code == 200 and bench.get("/api/thermal/setup").json()["pairs"] == [
        {"a": 1, "b": 2, "opposed": False}]
    assert bench.put("/api/thermal/setup", json={"pairs": [{"a": 1, "b": 1}]}).status_code == 400
    # Left as it was found: direct mode off, torque on, ceiling re-applied.
    control = bench.get("/api/hand/info").json()["control"]
    assert control["direct_motor_mode"] is False
    assert bench.get("/api/status").json()["torque_enabled"] is True
    # The mock reads Goal Current back as the current: the ceiling is on again.
    hand = bench.app.state.service.session.hand
    assert hand.get_motor_current(as_dict=True)[1] == ceiling


def test_finger_control_clamps_to_the_captured_range_behind_the_torque_gate(bench):
    """Fingers on the bench: joints are the operator's — a linear combination
    of motors and two captured ends in joint degrees — kept beside the bench
    config. Driving them is a run that refuses released motors, a coupling it
    cannot invert, unknown joints, and any target past the captured ends."""
    # MCP and PIP read as a sum and a difference of two shafts: mcp =
    # 0.5 (θ1 + θ2), pip = 0.5 (θ1 − θ2) (gains in joint deg per shaft deg).
    joints = [{"name": "index_mcp", "group": "index", "open_deg": 0.0, "closed_deg": 90.0,
               "terms": [{"motor": 1, "gain": 0.5}, {"motor": 2, "gain": 0.5}]},
              {"name": "index_pip", "group": "index", "open_deg": 0.0, "closed_deg": 100.0,
               "terms": [{"motor": 1, "gain": 0.5}, {"motor": 2, "gain": -0.5}]}]
    # The setup follows the bench, not the browser.
    assert bench.put("/api/fingers/setup", json={"joints": joints}).status_code == 200
    stored = bench.get("/api/fingers/setup").json()
    assert stored["joints"][1]["terms"][1] == {"motor": 2, "gain": -0.5}

    start = lambda **p: bench.post("/api/operation/finger_control/start",  # noqa: E731
                                   json={"params": p})
    assert bench.post("/api/fingers/targets", json={"targets": {"index_mcp": 1}}).status_code == 409
    # Nothing moves without torque, and it is per motor.
    assert start(joints=joints).status_code == 409
    assert bench.post("/api/motors/1/torque", json={"enabled": True}).status_code == 200
    assert start(joints=joints).status_code == 409
    assert bench.post("/api/motors/2/torque", json={"enabled": True}).status_code == 200
    bench.post("/api/control/pose_source", json={"mode": "estimate"})
    # Two joints with the same terms cannot be told apart; a joint on a motor
    # another coupling owns makes three joints on two motors.
    same = [joints[0], {**joints[1], "terms": joints[0]["terms"]}]
    assert start(joints=same).status_code == 400
    third = joints + [{"name": "ring", "open_deg": 0, "closed_deg": 10,
                       "terms": [{"motor": 2, "gain": 1}]}]
    assert start(joints=third).status_code == 400
    assert start(joints=[{**joints[0], "closed_deg": 0.5}]).status_code == 400
    response = start(joints=joints, speed_deg_s=2000)
    assert response.status_code == 200, response.text
    assert _wait_for(lambda: (_operation(bench) or {}).get("state") == "running")

    assert bench.post("/api/fingers/targets", json={"targets": {"thumb": 0.5}}).status_code == 404
    # A target past the end is clamped to it, never written past it.
    response = bench.post("/api/fingers/targets",
                          json={"targets": {"index_mcp": 7.0, "index_pip": -3.0}})
    assert response.status_code == 200, response.text
    assert response.json()["targets"] == {"index_mcp": 1.0, "index_pip": 0.0}

    def arrived():
        extra = (_operation(bench) or {}).get("extra") or {}
        by_name = {j["name"]: j for j in extra.get("joints", [])}
        mcp, pip = by_name.get("index_mcp"), by_name.get("index_pip")
        return (mcp and pip and mcp["position_deg"] is not None
                and abs(mcp["position_deg"] - 90.0) < 2.0
                and abs(pip["position_deg"]) < 2.0)
    assert _wait_for(arrived, timeout=10)
    # MCP closed with PIP open means both shafts at +90: the coupling, applied.
    shafts = {m["id"]: m["position"] for m in bench.get("/api/motors/direct").json()["motors"]}
    assert shafts[1] == pytest.approx(math.radians(90), abs=0.05)
    assert shafts[2] == pytest.approx(math.radians(90), abs=0.05)

    # A cycle walks the poses with the same clamping, and a hand on a slider
    # ends it rather than fighting it.
    poses = [{"name": "open", "targets": {"index_mcp": 0, "index_pip": 0}},
             {"name": "bad", "targets": {"index_mcp": 9, "index_pip": 1}}]
    assert bench.post("/api/fingers/cycle", json={"poses": poses[:1], "cycles": 1}).status_code == 400
    response = bench.post("/api/fingers/cycle", json={"poses": poses, "cycles": 0, "dwell_s": 0.1})
    assert response.status_code == 200, response.text

    def cycling():
        extra = (_operation(bench) or {}).get("extra") or {}
        return (extra.get("cycle") or {}).get("done", 0) >= 1
    assert _wait_for(cycling, timeout=10)
    assert bench.post("/api/fingers/targets", json={"targets": {"index_mcp": 0.5}}).status_code == 200
    assert _wait_for(lambda: ((_operation(bench) or {}).get("extra") or {}).get("cycle") is None)

    assert bench.post("/api/operation/stop").status_code == 200
    assert _wait_for(lambda: (_operation(bench) or {}).get("state") == "done")
    # Let go of the bus but not of the fingers: direct mode off, motors held.
    control = bench.get("/api/hand/info").json()["control"]
    assert control["direct_motor_mode"] is False
    assert control["control_source"] == "manual"
    assert control["held_motors"] == [1, 2]

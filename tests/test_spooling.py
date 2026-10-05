"""Spooling: the torque-wrench ceiling, the thermal guard, and the release
that ends every hold.

The simulated variant runs the REAL hold loop over an in-memory hand, so the
REST test exercises the same code path as hardware; the direct test drives
that loop to a stop mid-hold and checks what it leaves behind.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from orca_core.hand_config import OrcaHandConfig

from orca_ui.hand.operations import OperationStopped, spooling
from orca_ui.hand.operations.spooling import SimulatedSpoolHand, SpoolingRun
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"ramp_s": 0.1}


@pytest.fixture(autouse=True)
def _brisk_spooling(monkeypatch):
    monkeypatch.setattr(spooling, "TICK_S", 0.02)
    monkeypatch.setattr(spooling, "STALL_HOLD_S", 0.1)
    monkeypatch.setattr(spooling, "EXTRA_PERIOD_S", 0.02)
    monkeypatch.setattr(spooling, "TEMP_PERIOD_S", 0.02)
    monkeypatch.setattr(spooling, "WIGGLE_PERIOD_S", 0.02)
    monkeypatch.setattr(spooling, "WIGGLE_SETTLE_S", 0.02)


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


def _wait_awaiting(client, phase, options, timeout=15.0):
    def check():
        snapshot = _operation(client) or {}
        return (snapshot.get("state") == "awaiting_input"
                and snapshot.get("phase") == phase
                and (snapshot.get("awaiting") or {}).get("options") == options)
    assert _wait_for(check, timeout=timeout), \
        f"never awaited {options} in {phase}: {_operation(client)}"
    return _operation(client)


def _answer(client, value):
    return client.post("/api/operation/input", json={"value": value})


def test_spooling_one_by_one_tightens_under_the_ceiling_and_lets_go(client):
    start = "/api/operation/spooling/start"
    # A tighter spool than the ceiling allows is refused, never clamped; an
    # unknown joint never reaches a motor.
    assert client.post(start, json={"params": {"tighten_current_ma": 150}}
                       ).status_code == 400
    assert client.post(start, json={"params": {"joints": ["index_mcp", "nope"]}}
                       ).status_code == 400
    assert client.post(start, json={"params": {"joints": ["wrist"]}}
                       ).status_code == 400
    # The winding current stops at the motor family's register ceiling.
    assert client.post(start, json={"params": {"wind_current_ma": 5000}}
                       ).status_code == 400

    # Spools are visited in motor-ID order along the pack (index_pip is
    # motor 2, index_mcp motor 3), whatever order was asked for.
    response = client.post(start, json={"params": {
        **FAST, "mode": "one_by_one", "joints": ["index_mcp", "index_pip"],
        "tighten_current_ma": 80, "wind_current_ma": 400}})
    assert response.status_code == 200, response.text

    snapshot = _wait_awaiting(client, "seating", ["Next"])
    assert client.get("/api/status").json()["state"] == "maintenance"
    extra = snapshot["extra"]
    assert [m["joint"] for m in extra["motors"]] == ["index_pip", "index_mcp"]
    assert extra["active"] == "index_pip"
    assert [side["id"] for side in extra["sides"]] == ["A", "B"]
    assert extra["motors"][0]["side"] == "A"
    # Only the active motor is driven; the seating pull is the winding current.
    assert extra["motors"][0]["limit_ma"] == 400
    assert extra["motors"][1]["state"] == "pending"
    # Input outside the hold's options is not an answer.
    _answer(client, "Done")
    assert (_operation(client) or {}).get("phase") == "seating"

    _answer(client, "Next")
    _wait_awaiting(client, "attaching", ["Next"])
    _answer(client, "Next")
    snapshot = _wait_awaiting(client, "tightening", ["Next"])
    assert snapshot["extra"]["limit_ma"] == 80

    def reached():
        motors = (_operation(client) or {}).get("extra", {}).get("motors", [])
        return [m for m in motors if m["state"] == "reached"]
    at_torque = _wait_for(reached)
    assert [m["joint"] for m in at_torque] == ["index_pip"], _operation(client)
    assert at_torque[0]["current_ma"] <= 80

    # The second motor's run ends with Done; the first keeps holding meanwhile.
    _answer(client, "Next")
    snapshot = _wait_awaiting(client, "seating", ["Next"])
    assert snapshot["extra"]["active"] == "index_mcp"
    assert snapshot["extra"]["motors"][0]["done"] is True
    _answer(client, "Next")
    _wait_awaiting(client, "attaching", ["Next"])
    _answer(client, "Next")
    _wait_awaiting(client, "tightening", ["Done"])
    _answer(client, "Done")

    assert _wait_for(lambda: (_operation(client) or {}).get("state") == "done")
    result = _operation(client)["result"]
    assert result["released"] is True
    assert "index_pip" in result["reached"]
    assert _wait_for(
        lambda: client.get("/api/status").json()["state"] == "connected")


class _StubCtx:
    def __init__(self):
        self.stop_event = threading.Event()
        self.awaiting = None
        self.phase = None
        self.lines = []

    def set_phase(self, phase, detail=None, progress=None):
        self.phase = phase

    def set_progress(self, progress, detail=None):
        pass

    def set_extra(self, extra):
        pass

    def log(self, line):
        self.lines.append(line)

    def check_stop(self):
        if self.stop_event.is_set():
            raise OperationStopped()

    def sleep(self, seconds):
        if self.stop_event.wait(seconds):
            raise OperationStopped()

    def announce_input(self, prompt, options):
        self.awaiting = (prompt, options)

    def resume_running(self):
        self.awaiting = None


def test_spooling_hot_motor_holds_cool_and_stop_leaves_torque_off():
    config = OrcaHandConfig.from_config_path(materialize_mock_model())
    hand = SimulatedSpoolHand(config, ramp_s=0.1)
    ctx = _StubCtx()
    run = SpoolingRun(hand, ctx, mode="all", joints=["index_mcp", "index_pip"],
                      tighten_current_ma=60, wind_current_ma=200)
    mcp = config.joint_to_motor_map["index_mcp"]
    pip = config.joint_to_motor_map["index_pip"]
    outcome = {}

    def body():
        try:
            run.run()
        except OperationStopped:
            outcome["stopped"] = True

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    assert _wait_for(lambda: ctx.awaiting is not None)
    assert sorted(hand.torque) == sorted([mcp, pip])
    assert hand._limit[mcp] == 200

    # Near the rated ceiling the motor is dropped to a cool hold on its own,
    # and comes back once it has recovered.
    hand.temps[mcp] = 0.95 * hand.motor_client.max_operating_temp_c
    assert _wait_for(lambda: hand._limit[mcp] == 60)
    assert hand._limit[pip] == 200
    hand.temps[mcp] = 40.0
    assert _wait_for(lambda: hand._limit[mcp] == 200)

    # A servo rebooted by a power glitch wakes up limp with its EEPROM ceiling
    # as goal current. The watchdog re-arms it, limits first.
    hand.torque.remove(mcp)
    hand._limit[mcp] = 910.0
    assert _wait_for(lambda: mcp in hand.torque and hand._limit[mcp] == 200)
    assert run.extra()["motors"][1]["torque_drops"] == 1

    # Top spools go one at a time, lowest motor ID first: only the active
    # motor drops to the torque limit, the other keeps the winding hold.
    assert run.advance("Next")
    assert _wait_for(lambda: ctx.phase == "attaching")
    assert run.extra()["active"] == "index_pip"
    assert run.advance("Next")
    assert _wait_for(lambda: ctx.phase == "tightening")
    assert hand._limit[pip] == 60 and hand._limit[mcp] == 200

    ctx.stop_event.set()
    thread.join(timeout=5.0)
    assert outcome.get("stopped") is True
    assert hand.torque == []
    assert hand.control_mode == config.control_mode
    assert set(hand._limit.values()) == {float(config.max_current)}
    assert ctx.awaiting is None
    assert ctx.phase == "released"

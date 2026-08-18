"""MCP server tests: tool catalog, guards, error translation, telemetry.

The backend runs as a real uvicorn server on an ephemeral port (module
scope) because the MCP telemetry path dials ``/ws`` with the ``websockets``
client, which can't speak ASGI — TestClient would test a fork of the code.
MCP tools are exercised in-process via ``FastMCP.call_tool`` (full-fidelity
through the tool manager; no stdio subprocess), wrapped in ``asyncio.run``
to match this repo's sync-test convention.
"""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp.server.fastmcp.exceptions import ToolError

from orca_ui.hand.operations import Operation
from orca_ui.hand.states import ControlSource
from orca_ui.mcp import telemetry
from orca_ui.mcp.client import BackendClient, BackendError, _translate
from orca_ui.mcp.server import (ServerState, build_server,
                                build_server_with_state, confirm_gate,
                                mock_gate, state_block)
from orca_ui.mcp.settings import McpSettings
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


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


@pytest.fixture(scope="module")
def backend_url():
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False)
    app = create_app(settings)
    for op_cls in (FastOp, HoldOp, InputOp):
        app.state.operations.register(op_cls)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning",
                                           access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]},
                              daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"

    def _state():
        try:
            return httpx.get(url + "/api/status", timeout=1.0).json()["state"]
        except Exception:
            return None

    assert _wait_for(lambda: server.started, timeout=10)
    assert _wait_for(lambda: _state() == "connected", timeout=15)
    yield url
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture()
def mcp(backend_url):
    return build_server(McpSettings(url=backend_url))


@pytest.fixture(autouse=True)
def _leave_hand_safe(backend_url):
    # Every test ends de-escalated (torque off, operations/teleop stopped),
    # so module-scoped backend state never leaks across tests.
    yield
    httpx.post(backend_url + "/api/estop", timeout=5.0)
    _wait_for(lambda: not httpx.get(
        backend_url + "/api/status", timeout=1.0).json()["torque_enabled"])


def _call(mcp_server, _tool, **args):
    result = asyncio.run(mcp_server.call_tool(_tool, args))
    return json.loads(result[0].text)


def _tool_names(mcp_server):
    return [t.name for t in asyncio.run(mcp_server.list_tools())]


# ----- catalog & reads --------------------------------------------------------


def test_status_tool_happy_path(mcp):
    out = _call(mcp, "orca_get_status")
    assert out["hand"] == "mock (simulated)"
    assert out["connection"]["state"] == "connected"
    assert out["torque"].startswith("disabled")
    assert out["connection"]["capabilities"]["motors"] is True
    assert out["control_owner"] == "manual"


def test_tool_call_marks_last_activity(backend_url):
    """The idle watchdog (cli.py) reads state.last_activity to decide when
    to exit — every tool call, not just the initial handshake, must bump it."""
    mcp_server, state = build_server_with_state(McpSettings(url=backend_url))
    before = state.last_activity
    time.sleep(0.01)
    _call(mcp_server, "orca_get_status")
    assert state.last_activity > before


def test_estop_is_first_and_always_registered(mcp):
    names = _tool_names(mcp)
    assert names[0] == "orca_estop"
    assert len(names) == 22
    out = _call(mcp, "orca_estop")
    assert out["ok"] is True
    assert "torque disabled" in out["summary"]


def test_backend_unreachable_error():
    dead = build_server(McpSettings(url="http://127.0.0.1:1"))
    with pytest.raises(ToolError, match="uv run orca-ui --mock"):
        asyncio.run(dead.call_tool("orca_get_status", {}))
    # The e-stop failure path is distinct: it must NOT say "start the
    # backend" (wrong advice mid-incident) but point at the web UI / power.
    with pytest.raises(ToolError, match="e-stop request FAILED"):
        asyncio.run(dead.call_tool("orca_estop", {}))


def test_hand_info_and_library(mcp):
    info = _call(mcp, "orca_get_hand_info")
    assert info["mock"] is True
    assert "control" not in info
    assert all({"id", "rom", "neutral"} <= set(j) for j in info["joints"])
    library = _call(mcp, "orca_list_library")
    assert "fist" in library["poses"]["builtin"]
    assert any(d["name"] == "open_close" for d in library["demos"])


# ----- motion guards ------------------------------------------------------------


def test_motion_without_torque_translates_409(mcp):
    joint = _call(mcp, "orca_get_hand_info")["joints"][0]["id"]
    with pytest.raises(ToolError, match="orca_set_torque"):
        asyncio.run(mcp.call_tool(
            "orca_set_joints",
            {"angles": {joint: 0.0}, "verify": False}))


def test_translate_409_torque_gives_the_fix_exactly_once():
    # The backend detail already carries the prose advice; the MCP layer adds
    # only the tool that performs it, so the agent isn't told twice.
    message = _translate(409, "torque is disabled — enable it first")
    assert message.count("orca_set_torque") == 1
    assert "the hand is limp" not in message


def test_torque_enable_then_move_converges(mcp):
    # Mock backend: no confirm needed (the gate only exists on real hardware).
    out = _call(mcp, "orca_set_torque", enabled=True)
    assert out.get("refused") is not True
    assert out["torque_enabled"] is True
    assert out["state"]["hand"] == "mock (simulated)"
    assert "reminder" in out   # energized-hand nudge

    info = _call(mcp, "orca_get_hand_info")
    joint = next(j for j in info["joints"] if j["encoder_backed"])
    lo, hi = joint["rom"]
    target = round((lo + hi) / 2, 1)
    moved = _call(mcp, "orca_set_joints", angles={joint["id"]: target},
                  verify_timeout_s=5.0, tolerance_deg=3.0)
    assert moved["applied"] == {joint["id"]: target}
    assert moved["verification"]["converged"] is True

    parked = _call(mcp, "orca_park")
    assert parked["torque_disabled"] is True


def test_rom_violation_clamped_and_rejected(mcp):
    _call(mcp, "orca_set_torque", enabled=True)
    info = _call(mcp, "orca_get_hand_info")
    joint = info["joints"][0]
    lo, hi = joint["rom"]
    out = _call(mcp, "orca_set_joints", angles={joint["id"]: hi + 500},
                verify=False)
    assert out["applied"][joint["id"]] == hi
    assert out["clamped"][joint["id"]]["requested"] == hi + 500
    assert out["clamped"][joint["id"]]["rom"] == [lo, hi]
    with pytest.raises(ToolError, match="outside its ROM"):
        asyncio.run(mcp.call_tool("orca_set_joints", {
            "angles": {joint["id"]: hi + 500}, "clamp": False,
            "verify": False}))


def test_unknown_joint_rejected_before_backend(mcp):
    with pytest.raises(ToolError, match="unknown joints"):
        asyncio.run(mcp.call_tool(
            "orca_set_joints", {"angles": {"bogus_joint": 1.0},
                                "verify": False}))


def test_set_joints_advisory_notes(mcp):
    _call(mcp, "orca_set_torque", enabled=True)
    info = _call(mcp, "orca_get_hand_info")
    joint = next(j["id"] for j in info["joints"]
                 if j["rom"][1] - j["rom"][0] > 20)
    # Radians heuristic: small nonzero value on a wide-ROM joint.
    out = _call(mcp, "orca_set_joints", angles={joint: 1.0}, verify=False)
    assert any("look like radians" in n for n in out["notes"])
    # Rate advisory: fires on the 11th call inside 5 s, not before.
    for i in range(9):   # calls 2-10 (values > 3.5 keep the radians note off)
        out = _call(mcp, "orca_set_joints", angles={joint: 5.0 + i},
                    verify=False)
        assert not any("lossy" in n for n in out.get("notes", []))
    out = _call(mcp, "orca_set_joints", angles={joint: 20.0}, verify=False)
    assert any("lossy" in n and "replay" in n for n in out["notes"])


def test_apply_pose_builtin_neutral_and_unknown(mcp):
    _call(mcp, "orca_set_torque", enabled=True)
    out = _call(mcp, "orca_apply_pose", name="fist", verify_timeout_s=5.0)
    assert out["ok"] is True and out["angles"]
    assert out["verification"]["converged"] is True
    neutral = _call(mcp, "orca_apply_pose", name="neutral", verify=False)
    expected = {j["id"]: j["neutral"]
                for j in _call(mcp, "orca_get_hand_info")["joints"]}
    assert neutral["angles"] == expected
    with pytest.raises(ToolError, match="orca_list_library"):
        asyncio.run(mcp.call_tool("orca_apply_pose",
                                  {"name": "nonexistent-pose"}))


def test_park_refusal_paths_and_already_parked(mcp, backend_url):
    httpx.post(backend_url + "/api/operation/test.hold/start",
               json={}, timeout=5.0).raise_for_status()
    _wait_for(lambda: (httpx.get(backend_url + "/api/operation", timeout=1.0)
                       .json()["operation"] or {}).get("state") == "running")
    refused = _call(mcp, "orca_park")
    assert refused["refused"] is True
    assert "orca_control_operation" in refused["message"]
    _call(mcp, "orca_control_operation", action="stop")
    _call(mcp, "orca_get_operation", wait_s=5)
    httpx.post(backend_url + "/api/estop", timeout=5.0)   # ensure torque off
    parked = _call(mcp, "orca_park")
    assert parked["already_parked"] is True
    # Park's claim is observed, not asserted: the state block re-reads torque.
    assert parked["state"]["torque_enabled"] is False
    assert "reminder" not in parked          # nothing is energized to remind of


def test_configure_tactile_validation_and_apply(mcp):
    with pytest.raises(ToolError, match="mutually exclusive"):
        asyncio.run(mcp.call_tool("orca_configure_tactile",
                                  {"zero": True, "clear_zero": True}))
    with pytest.raises(ToolError, match="nothing to do"):
        asyncio.run(mcp.call_tool("orca_configure_tactile", {}))
    out = _call(mcp, "orca_configure_tactile", mode="combined")
    assert out["applied"] == {"mode": "combined"}


# ----- telemetry ------------------------------------------------------------------


def test_telemetry_snapshot_one_value_per_topic(mcp, backend_url):
    def _snap():
        out = _call(mcp, "orca_read_telemetry",
                    topics=["joints.measured", "motors.telemetry"])
        return out if not out.get("missing") else None

    # motors.telemetry ticks at 1 Hz — allow it a moment to first publish.
    out = _wait_for(_snap, timeout=10.0, interval=0.3)
    assert out, "telemetry topics never published"
    assert "angles" in out["topics"]["joints.measured"]
    assert "temps" in out["topics"]["motors.telemetry"]


def test_telemetry_window_sampling(mcp):
    out = _call(mcp, "orca_read_telemetry", topics=["joints.measured"],
                duration_s=1.0, sample_hz=10)
    samples = out["topics"]["joints.measured"]["samples"]
    # Upper bound is the sample budget; the lower bound is 2 because the
    # change filter collapses a still hand to just the bracketing frames.
    assert 2 <= len(samples) <= 11
    assert all("t" in s and "angles" in s["data"] for s in samples)
    assert samples[0]["t"] < samples[-1]["t"]


def test_change_filter_collapses_a_still_hand(mcp, backend_url):
    httpx.post(backend_url + "/api/estop", timeout=5.0)   # limp, then still

    def _quiet():
        out = _call(mcp, "orca_read_telemetry", topics=["joints.measured"],
                    duration_s=0.6, sample_hz=10)
        return out if out.get("dropped_unchanged") else None

    out = _wait_for(_quiet, timeout=10.0, interval=0.3)
    assert out, "a still hand never collapsed a single frame"
    assert out["dropped_unchanged"]["joints.measured"] >= 1
    assert out["topics"]["joints.measured"]["count"] >= 2   # first + last
    assert "deadband" in out["note_unchanged"]


# ----- change filter (pure, no backend) --------------------------------------------


def _frame(t, angles):
    return {"t": t, "data": {"angles": angles}}


def test_change_filter_drops_stillness_and_keeps_movement():
    still = [_frame(i * 0.1, {"index_mcp": 10.0 + 0.01 * i}) for i in range(6)]
    kept, dropped = telemetry._change_filter(still)
    assert [s["t"] for s in kept] == [still[0]["t"], still[-1]["t"]]
    assert dropped == 4

    moving = [_frame(i * 0.1, {"index_mcp": 10.0 * i}) for i in range(6)]
    kept, dropped = telemetry._change_filter(moving)
    assert len(kept) == 6 and dropped == 0


def test_change_filter_keeps_last_frame_so_preview_stays_fresh():
    # orca_get_camera_preview reads samples[-1]; it must be the newest frame.
    frames = [_frame(i * 0.1, {"index_mcp": 10.0}) for i in range(5)]
    kept, _ = telemetry._change_filter(frames)
    assert kept[-1] is frames[-1]


def test_change_filter_never_touches_undeadbanded_payloads():
    # teleop.preview (jpeg) / stats have no deadband — pass them through whole.
    frames = [{"t": i * 0.1, "data": {"jpeg": "same"}} for i in range(4)]
    kept, dropped = telemetry._change_filter(frames)
    assert len(kept) == 4 and dropped == 0


def test_changed_applies_each_groups_own_unit():
    # 5 mA of current wobble is noise (band 20 mA); 0.6 °C is a real step.
    a = {"temps": {"1": 40.0}, "currents": {"1": 100.0}}
    b = {"temps": {"1": 40.1}, "currents": {"1": 105.0}}
    c = {"temps": {"1": 40.8}, "currents": {"1": 105.0}}
    assert not telemetry._changed(a, b)
    assert telemetry._changed(b, c)


def test_changed_handles_nested_vectors_and_shape_drift():
    a = {"forces": {"thumb": [0.0, 0.0, 1.0]}}
    assert not telemetry._changed(a, {"forces": {"thumb": [0.0, 0.0, 1.1]}})
    assert telemetry._changed(a, {"forces": {"thumb": [0.0, 0.0, 1.4]}})
    # A shape or key change is never silently filtered away.
    assert telemetry._changed(a, {"forces": {"thumb": [0.0, 1.0]}})
    assert telemetry._changed(a, {"forces": {"index": [0.0, 0.0, 1.0]}})


def test_telemetry_unknown_topic_lists_valid(backend_url):
    with pytest.raises(BackendError, match="valid topics"):
        asyncio.run(telemetry.ws_snapshot(backend_url, ["joints.bogus"]))
    # And the tool layer rejects it even earlier (Literal enum).
    mcp_server = build_server(McpSettings(url=backend_url))
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.call_tool(
            "orca_read_telemetry", {"topics": ["joints.bogus"]}))


def test_telemetry_missing_topic_times_out_gracefully(mcp):
    start = time.time()
    out = _call(mcp, "orca_read_telemetry", topics=["teleop.targets"])
    assert time.time() - start < 6.0
    assert out["missing"] == ["teleop.targets"]
    assert out["topics"]["teleop.targets"] is None


# ----- operations ------------------------------------------------------------------


def test_operation_wait_reaches_terminal_state(mcp, backend_url):
    httpx.post(backend_url + "/api/operation/test.fast/start",
               json={}, timeout=5.0).raise_for_status()
    out = _call(mcp, "orca_get_operation", wait_s=10)
    assert out["operation"]["state"] == "done"
    assert out["operation"]["result"] == {"count": 3}
    assert out["timed_out"] is False
    assert any("line 2" in line for line in out["log"])


def test_operation_conflict_names_running_op(mcp, backend_url):
    httpx.post(backend_url + "/api/operation/test.hold/start",
               json={}, timeout=5.0).raise_for_status()
    _wait_for(lambda: (httpx.get(backend_url + "/api/operation", timeout=1.0)
                       .json()["operation"] or {}).get("state") == "running")
    with pytest.raises(ToolError, match="test.hold"):
        asyncio.run(mcp.call_tool(
            "orca_start_operation", {"kind": "demo", "name": "open_close"}))
    stopped = _call(mcp, "orca_control_operation", action="stop")
    assert stopped["ok"] is True
    out = _call(mcp, "orca_get_operation", wait_s=5)
    assert out["operation"]["state"] in ("done", "error")


def test_operation_awaiting_input_flow(mcp, backend_url):
    httpx.post(backend_url + "/api/operation/test.input/start",
               json={}, timeout=5.0).raise_for_status()
    out = _call(mcp, "orca_get_operation", wait_s=5)
    assert out["operation"]["state"] == "awaiting_input"
    assert out["operation"]["awaiting"]["prompt"] == "continue?"
    _call(mcp, "orca_send_operation_input", value="yes")
    out = _call(mcp, "orca_get_operation", wait_s=5)
    assert out["operation"]["state"] == "done"
    assert out["operation"]["result"] == {"answer": "yes"}


# ----- guards & catalog modes -------------------------------------------------------


def test_confirm_gate_refuses_on_real_hardware_only():
    class _DeadBackend:
        async def get(self, path):
            raise BackendError("down")

    class _FakeState:
        backend = _DeadBackend()

        def __init__(self, real):
            self._real = real

        async def is_real(self, fresh=False):
            return self._real

        async def hand_summary(self):
            return {"model_name": "orcahand_v1", "side": "right",
                    "mock": not self._real}

    real = asyncio.run(confirm_gate(_FakeState(True), False, "What: X."))
    assert real["refused"] is True
    assert real["retryable"] is False
    assert "confirm=true" in real["message"]
    assert "orca_estop" in real["message"]
    assert real["state"]["hand"] == "REAL HARDWARE (orcahand_v1, right)"
    assert asyncio.run(confirm_gate(_FakeState(True), True, "X")) is None
    assert asyncio.run(confirm_gate(_FakeState(False), False, "X")) is None


def test_mock_gate_refuses_real_hardware():
    class _FakeState:
        settings = McpSettings(url="http://unused", require_mock=True)

        async def is_real(self, fresh=False):
            return True

    out = asyncio.run(mock_gate(_FakeState()))
    assert out["refused"] is True
    assert out["retryable"] is False
    assert "--require-mock" in out["message"]
    assert "Restart the backend with --mock" in out["message"]


def test_state_block_fails_toward_real_when_backend_down():
    class _DeadBackend:
        async def get(self, path):
            raise BackendError("down")

    class _DeadState:
        backend = _DeadBackend()

        async def hand_summary(self, fresh=False):
            raise BackendError("down")

    block = asyncio.run(state_block(_DeadState()))
    assert block == {"hand": "unknown — treat as REAL"}


def _fake_real_server(backend_url, **settings_kwargs):
    """Tools registered on a state that REPORTS real hardware while actually
    talking to the mock backend — for exercising the real-only guard paths."""
    from mcp.server.fastmcp import FastMCP

    from orca_ui.mcp.tools import register_tools

    settings = McpSettings(url=backend_url, **settings_kwargs)
    state = ServerState(BackendClient(backend_url), settings)

    async def _fake_is_real(fresh=False):
        return True

    state.is_real = _fake_is_real
    server = FastMCP("orca_hand_mcp_fake_real")
    register_tools(server, state)
    return server


def test_torque_ack_once_latch_on_real_hardware(backend_url):
    server = _fake_real_server(backend_url)
    refused = _call(server, "orca_set_torque", enabled=True)
    assert refused["refused"] is True
    assert "confirm=true" in refused["message"]
    ok = _call(server, "orca_set_torque", enabled=True, confirm=True)
    assert ok["torque_enabled"] is True
    # Latched: later enables in the same server session are friction-free.
    again = _call(server, "orca_set_torque", enabled=True)
    assert again.get("refused") is not True
    # But a fresh server (new session) starts unacknowledged again.
    fresh = _fake_real_server(backend_url)
    assert _call(fresh, "orca_set_torque", enabled=True)["refused"] is True


def test_require_mock_on_real_gates_escalation_not_deescalation(backend_url):
    server = _fake_real_server(backend_url, require_mock=True)
    # Escalations refuse...
    assert _call(server, "orca_set_torque", enabled=True)["refused"] is True
    assert _call(server, "orca_control_operation",
                 action="resume")["refused"] is True
    # ...de-escalation stays free: park disables torque (enabled via raw
    # REST, simulating a human in the browser) but skips the neutral MOVE.
    httpx.post(backend_url + "/api/torque/enable", timeout=5.0)
    parked = _call(server, "orca_park")
    assert parked["torque_disabled"] is True
    assert parked["neutral"] is False
    assert "--require-mock" in parked["note"]


def test_read_only_catalog(backend_url):
    ro = build_server(McpSettings(url=backend_url, read_only=True))
    names = _tool_names(ro)
    assert names[0] == "orca_estop"
    assert "orca_get_status" in names
    assert "orca_set_joints" not in names
    assert "orca_set_torque" not in names
    assert len(names) == 7
    assert _call(ro, "orca_get_status")["connection"]["state"] == "connected"


def test_require_mock_allows_mock_backend(backend_url):
    guarded = build_server(McpSettings(url=backend_url, require_mock=True))
    out = _call(guarded, "orca_set_torque", enabled=True)
    assert out.get("refused") is not True
    assert out["torque_enabled"] is True

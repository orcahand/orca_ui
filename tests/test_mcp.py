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
from orca_ui.mcp.client import BackendError
from orca_ui.mcp.server import (build_server, confirm_gate)
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


def _call(mcp_server, _tool, **args):
    result = asyncio.run(mcp_server.call_tool(_tool, args))
    return json.loads(result[0].text)


def _tool_names(mcp_server):
    return [t.name for t in asyncio.run(mcp_server.list_tools())]


# ----- catalog & reads --------------------------------------------------------


def test_estop_is_first_and_always_registered(mcp):
    names = _tool_names(mcp)
    assert names[0] == "orca_estop"
    assert len(names) == 22
    out = _call(mcp, "orca_estop")
    assert out["ok"] is True
    assert "torque disabled" in out["summary"]


# ----- motion guards ------------------------------------------------------------


def test_motion_without_torque_translates_409(mcp):
    joint = _call(mcp, "orca_get_hand_info")["joints"][0]["id"]
    with pytest.raises(ToolError, match="orca_set_torque"):
        asyncio.run(mcp.call_tool(
            "orca_set_joints",
            {"angles": {joint: 0.0}, "verify": False}))


# ----- telemetry ------------------------------------------------------------------


# ----- change filter (pure, no backend) --------------------------------------------


# ----- operations ------------------------------------------------------------------


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

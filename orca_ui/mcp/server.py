"""FastMCP server factory + the shared guard machinery.

Safety stance (careless-agent model, not malice): confirm gates are enforced
only against REAL hardware so agents developing on --mock never learn to
auto-confirm; de-escalation (e-stop, torque off, park, stop/disengage) is
always friction-free; every refusal states physical consequences and points
at orca_estop.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from orca_ui.mcp.client import BackendClient, BackendError
from orca_ui.mcp.settings import McpSettings

HAND_INFO_TTL_S = 60.0

INSTRUCTIONS = """MCP access to an ORCA robotic hand through the orca-ui backend.

This server may be connected to REAL HARDWARE — check the `hand` field of
orca_get_status before any motion; everything you command happens physically.
The backend is shared with the browser UI: a human may own control (teleop or
an operation); never take control from them without being asked.

Ground rules:
- orca_get_status first; motion needs torque enabled AND manual control.
- Angles are DEGREES everywhere.
- When you are done moving the hand, leave it safe: orca_park (neutral +
  torque off) unless the user wants the pose held.
- If anything looks wrong physically, call orca_estop — always safe, never
  gated, also reachable from the web UI."""


class ServerState:
    """Shared per-server state: backend client, hand-info cache, latches."""

    def __init__(self, backend: BackendClient, settings: McpSettings):
        self.backend = backend
        self.settings = settings
        self.torque_acknowledged = False     # ack-once latch (real hardware)
        self.set_joints_times: list[float] = []
        self._summary: dict | None = None
        self._summary_at = 0.0

    def invalidate_hand_summary(self) -> None:
        self._summary = None

    def note_status(self, status: dict) -> None:
        """Drop the cached summary when a status snapshot names a different
        model. The backend re-derives the model from the hardware, so ROMs and
        neutral poses can change under a live server — they must not ride out
        the TTL belonging to the hand that was unplugged."""
        model = status.get("model")
        if (model and self._summary is not None
                and self._summary.get("model_name") != model):
            self._summary = None

    async def hand_summary(self, fresh: bool = False) -> dict:
        """Condensed /api/hand/info (60 s TTL): identity, mock flag, ROMs,
        neutral pose. Invalidated on any fetch failure — fail toward REAL.
        ``fresh=True`` bypasses the cache (safety gates re-verify the mock
        flag so a mock→real backend swap can't ride the TTL)."""
        now = time.monotonic()
        if (not fresh and self._summary is not None
                and now - self._summary_at < HAND_INFO_TTL_S):
            return self._summary
        try:
            info = await self.backend.get("/api/hand/info")
        except BackendError:
            self._summary = None
            raise
        self._summary = {
            "model_name": info.get("model_name"),
            "side": info.get("side"),
            "mock": bool(info.get("mock", False)),
            "roms": {j["id"]: (float(j["rom"][0]), float(j["rom"][1]))
                     for j in info.get("joints", [])},
            "neutral": {j["id"]: j["neutral"] for j in info.get("joints", [])},
        }
        self._summary_at = now
        return self._summary

    async def is_real(self, fresh: bool = False) -> bool:
        return not (await self.hand_summary(fresh=fresh))["mock"]


async def state_block(state: ServerState) -> dict:
    """Best-effort snapshot appended to every mutating response, so torque /
    ownership / real-vs-mock stay inside the agent's context window."""
    out: dict = {}
    backend = state.backend
    try:
        status = await backend.get("/api/status")
        state.note_status(status)
        out["torque_enabled"] = bool(status.get("torque_enabled"))
    except BackendError:
        pass
    try:
        summary = await state.hand_summary()
        out["hand"] = (
            "mock (simulated)" if summary["mock"]
            else f"REAL HARDWARE ({summary['model_name']}, {summary['side']})")
    except BackendError:
        out["hand"] = "unknown — treat as REAL"
    try:
        control = (await backend.get("/api/hand/info")).get("control", {})
        out["control_owner"] = control.get("control_owner")
        out["max_current_ma"] = control.get("max_current")
    except BackendError:
        pass
    try:
        op = (await backend.get("/api/operation")).get("operation")
        out["operation"] = (
            {"kind": op.get("kind"), "state": op.get("state")} if op else None)
    except BackendError:
        pass
    return out


async def with_state(state: ServerState, payload: dict) -> dict:
    block = await state_block(state)
    payload["state"] = block
    if block.get("torque_enabled"):
        payload["reminder"] = (
            "Hand is energized and will hold its last target indefinitely — "
            "orca_park or orca_set_torque(enabled=false) when done.")
    return payload


def refusal(message: str, block: dict | None = None) -> dict:
    out = {
        "refused": True,
        "retryable": False,
        "message": (message + " If anything is wrong physically, call "
                    "orca_estop."),
    }
    if block is not None:
        out["state"] = block
    return out


async def confirm_gate(state: ServerState, confirm: bool,
                       what: str) -> dict | None:
    """Refusal dict when real-hardware acknowledgment is missing; None to
    proceed. Never enforced against a mock backend (the field is ignored)."""
    if not await state.is_real(fresh=True):
        return None
    if confirm:
        return None
    summary = await state.hand_summary()
    block = await state_block(state)
    return refusal(
        "REFUSED — real-hardware acknowledgment required. "
        f"Hand: '{summary['model_name']}' ({summary['side']}), mock=false — "
        f"this is a PHYSICAL hand. {what} "
        "If the user wants this, retry with confirm=true (confirm is only "
        "required on real hardware — mock backends never need it). For safe "
        "testing, run the backend with --mock. Do not retry without changing "
        "something.",
        block,
    )


async def mock_gate(state: ServerState) -> dict | None:
    """--require-mock: refuse escalating mutations against real hardware."""
    if not state.settings.require_mock:
        return None
    try:
        if not await state.is_real(fresh=True):
            return None
    except BackendError:
        raise   # unreachable backend — the tool's own call would fail anyway
    return refusal(
        "--require-mock is set on this MCP server, and the backend reports "
        "REAL hardware — mutating tools are disabled. Restart the backend "
        "with --mock, or restart orca-ui-mcp without --require-mock.")


def build_server(settings: McpSettings) -> FastMCP:
    backend = BackendClient(settings.url, timeout=settings.timeout)
    state = ServerState(backend, settings)

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        # The client is constructed eagerly (httpx binds lazily); the
        # lifespan's only job is cleanup. No startup probe: the server must
        # boot with no backend running — tools report reachability instead.
        try:
            yield {}
        finally:
            await backend.aclose()

    mcp = FastMCP("orca_hand_mcp", instructions=INSTRUCTIONS,
                  lifespan=lifespan)
    from orca_ui.mcp.tools import register_tools
    register_tools(mcp, state)
    return mcp

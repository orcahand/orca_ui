"""HTTP client for the running backend, with agent-facing error translation.

Every backend failure becomes a :class:`BackendError` whose message is
written for the calling agent: it states what is wrong and which tool leads
out of it. Raising is the whole error story — FastMCP turns tool exceptions
into error results the agent reads.
"""

from __future__ import annotations

import httpx


def unreachable_hint(url: str) -> str:
    return (
        f"orca-ui backend not reachable at {url} — start it first: "
        "`uv run orca-ui --mock` (simulated hand) or `uv run orca-ui` "
        "(real hardware), then retry."
    )


class BackendError(Exception):
    """Backend/transport failure with an agent-actionable message."""


def _translate(status: int, detail: str) -> str:
    low = detail.lower()
    if status == 503:
        return (f"hand not connected: {detail} — check orca_get_status; "
                "orca_reconnect may help.")
    if status == 409:
        if "owned by teleop" in low:
            return (
                f"conflict: {detail}. An active teleop session is most likely "
                "a HUMAN operator tracking their own hand — do not take "
                "control unless the user explicitly asked you to. If they "
                "did: orca_teleop_stop(action='disengage'), then retry. "
                "Emergency only: orca_estop (stops teleop AND disables "
                "torque). Do not retry this call unchanged."
            )
        if "owned by" in low:
            return (
                f"conflict: {detail}. An operation owns the hand until it "
                "finishes. Wait with orca_get_operation(wait_s=...) or stop "
                "it with orca_control_operation(action='stop') — if a human "
                "started it from the browser, ask the user first. Do not "
                "retry while it runs."
            )
        if "already running" in low:
            return (f"conflict: {detail} — orca_get_operation(wait_s=...) to "
                    "wait for it, or orca_control_operation(action='stop').")
        if "torque" in low:
            # The backend detail already says what to do in prose; only add
            # the tool that does it, or the agent reads the same advice twice.
            return f"conflict: {detail} (orca_set_torque(enabled=true))."
        return f"conflict: {detail}"
    if status == 404:
        return f"not found: {detail}"
    if status == 400:
        return f"rejected: {detail}"
    return f"backend error (HTTP {status}): {detail}"


class BackendClient:
    """Shared async HTTP client bound to one backend URL."""

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url.rstrip("/")
        # No keep-alive: pooled connections bind to the event loop they were
        # created on, and embedders (tests, sync wrappers) may drive tools
        # from short-lived loops. Fresh localhost connections are ~free.
        self._http = httpx.AsyncClient(
            base_url=self.url, timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, json: dict | None = None):
        try:
            response = await self._http.request(method, path, json=json)
        except httpx.TransportError as e:
            raise BackendError(unreachable_hint(self.url)) from e
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise BackendError(_translate(response.status_code, str(detail)))
        return response.json()

    async def get(self, path: str):
        return await self.request("GET", path)

    async def post(self, path: str, json: dict | None = None):
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: dict | None = None):
        return await self.request("PUT", path, json=json)

    async def delete(self, path: str):
        return await self.request("DELETE", path)

    async def estop(self) -> dict:
        """Dedicated e-stop path: short timeout, one retry on transport
        errors, no dependence on any cache or translation branch."""
        last: Exception | None = None
        for _ in range(2):
            try:
                response = await self._http.post("/api/estop", timeout=2.0)
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
        raise BackendError(
            f"e-stop request FAILED ({last}) — the MCP server could not "
            f"reach the backend at {self.url}. If the hand is moving, use "
            "the web UI e-stop or cut power."
        )

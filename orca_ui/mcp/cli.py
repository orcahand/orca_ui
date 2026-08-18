"""``orca-ui-mcp`` entry point (stdio transport).

stdout belongs to the MCP protocol — the banner and any logging go to
stderr. The backend does not need to be running: tools report an actionable
"backend not reachable" error instead of the server failing to boot.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import anyio

from orca_ui.mcp.settings import DEFAULT_URL, McpSettings

# A stdio server outlives its host if the host ever dies without closing the
# pipe (a killed terminal, a crashed client) — nothing then tells this
# process to exit, and it's easy to forget it's still holding the backend's
# hand port. Idle-shutdown is the backstop: 0 disables it.
DEFAULT_IDLE_TIMEOUT_HOURS = 3.0
IDLE_CHECK_INTERVAL_S = 60.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orca-ui-mcp",
        description="MCP server exposing a running orca-ui backend to AI "
                    "agents (start the backend separately: orca-ui --mock "
                    "or orca-ui).")
    parser.add_argument(
        "--url", default=os.environ.get("ORCA_UI_URL", DEFAULT_URL),
        help="backend base URL (env ORCA_UI_URL; default %(default)s)")
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="HTTP timeout in seconds (default %(default)s)")
    parser.add_argument(
        "--read-only", action="store_true",
        help="register only read tools (plus e-stop)")
    parser.add_argument(
        "--require-mock", action="store_true",
        help="refuse mutating tools unless the backend reports a mock hand "
             "(for unattended agent runs)")
    parser.add_argument(
        "--idle-timeout-hours", type=float,
        default=float(os.environ.get("ORCA_UI_MCP_IDLE_TIMEOUT_HOURS",
                                     DEFAULT_IDLE_TIMEOUT_HOURS)),
        help="exit if no tool has been called for this many hours (env "
             "ORCA_UI_MCP_IDLE_TIMEOUT_HOURS; default %(default)s; "
             "0 disables)")
    return parser.parse_args(argv)


async def _run_until_idle_or_closed(mcp, state, idle_timeout_s: float) -> None:
    """Run the server; also exit if idle_timeout_s passes with no tool call.

    stdin closing (the normal case — the host process exited) already ends
    ``run_stdio_async`` on its own; the watchdog only covers the case where
    that never happens.
    Cancellation can't reach the "exit" case: run_stdio_async's stdin read
    runs synchronously in a worker thread (stdio_server wraps a blocking
    TextIOWrapper), and anyio has no way to interrupt a thread parked on a
    blocking syscall — cancelling the scope would just leave that thread
    stuck forever with nothing left to notice. os._exit is the only thing
    that actually works here; the process is leaving anyway, so skipping
    cleanup (an httpx client close) costs nothing.
    """
    if idle_timeout_s <= 0:
        await mcp.run_stdio_async()
        return

    async with anyio.create_task_group() as tg:
        async def watchdog() -> None:
            while True:
                await anyio.sleep(IDLE_CHECK_INTERVAL_S)
                idle_s = time.monotonic() - state.last_activity
                if idle_s >= idle_timeout_s:
                    print(f"orca-ui-mcp: idle for {idle_s / 3600:.1f}h "
                          f"(limit {idle_timeout_s / 3600:.1f}h) — exiting",
                          file=sys.stderr)
                    os._exit(0)

        tg.start_soon(watchdog)
        await mcp.run_stdio_async()
        tg.cancel_scope.cancel()   # stdin closed — stop the watchdog too


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = McpSettings(url=args.url.rstrip("/"), timeout=args.timeout,
                           read_only=args.read_only,
                           require_mock=args.require_mock)
    mode = " [read-only]" if settings.read_only else ""
    mode += " [require-mock]" if settings.require_mock else ""
    idle_timeout_s = args.idle_timeout_hours * 3600.0
    mode += (f" [idle-timeout {args.idle_timeout_hours:g}h]"
             if idle_timeout_s > 0 else " [idle-timeout disabled]")
    print(f"orca-ui-mcp: serving orca_hand_mcp over stdio -> "
          f"{settings.url}{mode}", file=sys.stderr)

    from orca_ui.mcp.server import build_server_with_state
    mcp, state = build_server_with_state(settings)
    anyio.run(_run_until_idle_or_closed, mcp, state, idle_timeout_s)


if __name__ == "__main__":
    main()

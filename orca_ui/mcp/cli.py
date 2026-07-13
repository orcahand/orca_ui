"""``orca-ui-mcp`` entry point (stdio transport).

stdout belongs to the MCP protocol — the banner and any logging go to
stderr. The backend does not need to be running: tools report an actionable
"backend not reachable" error instead of the server failing to boot.
"""

from __future__ import annotations

import argparse
import os
import sys

from orca_ui.mcp.settings import DEFAULT_URL, McpSettings


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = McpSettings(url=args.url.rstrip("/"), timeout=args.timeout,
                           read_only=args.read_only,
                           require_mock=args.require_mock)
    mode = " [read-only]" if settings.read_only else ""
    mode += " [require-mock]" if settings.require_mock else ""
    print(f"orca-ui-mcp: serving orca_hand_mcp over stdio -> "
          f"{settings.url}{mode}", file=sys.stderr)

    from orca_ui.mcp.server import build_server
    build_server(settings).run()   # stdio is FastMCP's default transport


if __name__ == "__main__":
    main()

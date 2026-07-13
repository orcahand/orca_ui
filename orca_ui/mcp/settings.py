"""Resolved MCP server configuration (mirrors the UiSettings pattern)."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_URL = "http://127.0.0.1:5001"


@dataclass(frozen=True)
class McpSettings:
    url: str = DEFAULT_URL
    timeout: float = 10.0            # HTTP timeout; long polls pace themselves
    read_only: bool = False          # register only read tools (+ e-stop)
    require_mock: bool = False       # refuse mutations unless backend is mock

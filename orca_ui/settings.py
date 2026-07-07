"""Resolved runtime settings shared by the CLI, server, and hand service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiSettings:
    """Everything the server needs to run, resolved once by the CLI.

    ``config_path`` always points at a concrete ``config.yaml`` (the CLI
    resolves ``--config``/``--model``/``--side``/``--mock`` down to a file
    before the server starts).
    """

    config_path: str
    mock: bool = False
    engage_feedback: bool = True
    motors_enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 5001
    open_browser: bool = True

    # Browser-facing stream rates (Hz). Producers run at hardware rates; the
    # broadcaster decimates to these. Tunable for slow machines / debugging.
    fast_hz: float = 60.0
    mid_hz: float = 10.0
    slow_hz: float = 1.0

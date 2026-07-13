"""MCP server exposing the running orca-ui backend to AI agents.

A pure network client of the backend's REST + WebSocket API — the same
surface the browser uses, so the backend stays the single owner of the hand
and its arbitration (control sources, torque gates, e-stop) applies to
agents exactly as it does to humans. Nothing in this package imports
orca_core or orca_ui.hand.

Launch with ``orca-ui-mcp`` (stdio transport); the backend must be started
separately (``orca-ui --mock`` for the simulated hand).
"""

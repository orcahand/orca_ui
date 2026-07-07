"""Neutralize orca_core behaviors that assume an interactive terminal.

``OrcaHand.connect()`` falls back to a curses port picker
(``get_and_choose_port``) after auto-detection fails — inside a server that
would hijack the terminal and block the supervisor thread forever. Rebinding
the name in ``hardware_hand``'s namespace makes that fallback return ``None``,
so ``connect()`` cleanly returns ``(False, "Connection failed: No port
selected")`` instead.

TODO: upstream an ``interactive: bool = True`` parameter on
``OrcaHand.connect()`` so this monkeypatch can go away.
"""

from __future__ import annotations

_applied = False


def neutralize_interactive_picker() -> None:
    global _applied
    if _applied:
        return
    import orca_core.hardware_hand as hardware_hand

    hardware_hand.get_and_choose_port = lambda: None
    _applied = True

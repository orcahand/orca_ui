"""Hardware tests: the console's Tests tab walks a developer through a plan of
hands-on steps and automatic checks on one connected hand, and keeps every
result on disk under ``<bench>/<hand>/tests/`` for people and agents to read.

The tab is shown when the console runs a development orca_core, or when it
was started with ``--hardware-tests``.
"""

from __future__ import annotations


def tab_enabled(settings) -> bool:
    if getattr(settings, "hardware_tests", False):
        return True
    from orca_ui.core_source import resolve_cached

    return resolve_cached().is_development

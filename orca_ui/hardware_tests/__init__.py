"""Hardware tests: the console's Tests tab walks a developer through a plan of
hands-on steps and automatic checks on one connected hand, and keeps every
result on disk under ``<bench>/<hand>/tests/`` for people and agents to read.

The tab is shown only when the console was started with ``--hardware-tests``.
"""

from __future__ import annotations


def tab_enabled(settings) -> bool:
    return bool(getattr(settings, "hardware_tests", False))

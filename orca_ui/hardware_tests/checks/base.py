"""The interface every automatic check implements, and the registry the runner
looks checks up in.

A check is a function ``check(ctx) -> CheckResult`` registered under the name
a step's ``check:`` field uses. It runs on the runner's thread, may take
minutes, and must call ``ctx.check_stop()`` between slow parts so Stop works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional, Protocol

from orca_ui.hardware_tests.model import CheckResult, HandFacts, Step

if TYPE_CHECKING:
    from pathlib import Path

    from orca_ui.hand.service import HandService


class SideRunner(Protocol):
    """Runs a recorder scenario with one side's orca_core while the console
    has released the hand. Implemented in ``hardware_tests/sides.py``."""

    def available(self, side: str) -> Optional[str]:
        """``None`` when ``side`` ("main" or "branch") can run, else why not."""

    def run(self, side: str, scenario: str, args: dict, out_dir: "Path") -> dict:
        """Run ``scenario`` and return the recorder's ``result.json`` contents."""


class CheckContext(Protocol):
    step: Step
    hand: HandFacts
    service: "HandService"
    sides: SideRunner
    out_dir: "Path"
    """The step's folder in the feature's session folder; checks write files here."""

    def log(self, line: str) -> None:
        """Append a line to the session's event log and the tab's live log."""

    def progress(self, fraction: float, detail: str = "") -> None: ...

    def check_stop(self) -> None:
        """Raise ``StopRequested`` if the person pressed Stop."""

    def step_result(self, step_id: str) -> Optional[dict]:
        """Another step's stored result in this session, e.g. to analyse its readings."""


class StopRequested(Exception):
    pass


CheckFn = Callable[[CheckContext], CheckResult]
_REGISTRY: dict[str, CheckFn] = {}


def register(name: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise ValueError(f"check {name!r} is registered twice")
        _REGISTRY[name] = fn
        return fn
    return decorator


def get_check(name: str) -> Optional[CheckFn]:
    return _REGISTRY.get(name)


def registered_checks() -> frozenset[str]:
    return frozenset(_REGISTRY)

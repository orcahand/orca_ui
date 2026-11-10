"""The registered checks: importing this package registers every check.

``console`` holds the checks that use the running console, ``evidence`` the
ones that judge a hands-on step from what the session recorded, ``software``
the test-suite run, and ``compare`` the ones that run a scenario with main's
and the branch's orca_core. A
``compare`` module that fails to import does not stop the console checks from
working; looking up one of its checks then raises with the import error.
"""

from __future__ import annotations

from typing import Optional

from orca_ui.hardware_tests.checks import console, evidence, software  # noqa: F401  (registers)
from orca_ui.hardware_tests.checks.base import CheckFn, get_check, registered_checks

COMPARE_IMPORT_ERROR: Optional[BaseException] = None
try:
    from orca_ui.hardware_tests.checks import compare  # noqa: F401  (registers)
except ImportError as e:
    COMPARE_IMPORT_ERROR = e


class CheckNotFound(LookupError):
    pass


def lookup(name: str) -> CheckFn:
    """The check registered as ``name``; raises with the reason when it is not."""
    fn = get_check(name)
    if fn is not None:
        return fn
    if COMPARE_IMPORT_ERROR is not None:
        raise CheckNotFound(
            f"check {name!r} is not registered, and orca_ui/hardware_tests/checks/compare.py "
            f"could not be imported: {COMPARE_IMPORT_ERROR!r}")
    raise CheckNotFound(f"check {name!r} is not registered")


__all__ = ["COMPARE_IMPORT_ERROR", "CheckNotFound", "lookup", "registered_checks"]

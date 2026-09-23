"""Dev mode must never reach a commit.

``orca-dev local`` points this checkout at an orca_core next to it. uv has no
local-only override file, so that edit lands in tracked files: ``pyproject.toml``
and ``uv.lock``. A relative path is a fact about one machine, so a commit
carrying it makes the project uninstallable anywhere else.

These tests read the *committed* files, not the working tree, so they pass
while you are in dev mode and fail only once the override reaches a commit.
"""

import subprocess

import pytest

from orca_ui.core_source import has_dev_override, lock_has_dev_source

FIX = ("Your working tree may stay in dev mode; only the commit must be clean.\n"
       "    uv run orca-dev release   # drop the override\n"
       "    uv lock && git add pyproject.toml uv.lock\n"
       "    uv run orca-dev local     # back to dev mode")


def _committed(path: str) -> str:
    """The file as of HEAD, or skip when there is no git history to read."""
    try:
        done = subprocess.run(["git", "show", f"HEAD:{path}"],
                              capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("git is not available")
    if done.returncode != 0:
        pytest.skip(f"{path} is not in HEAD (installed from a dist?)")
    return done.stdout


def test_committed_pyproject_has_no_orca_core_source():
    assert not has_dev_override(_committed("pyproject.toml")), (
        f"pyproject.toml in HEAD carries a [tool.uv.sources] entry for "
        f"orca_core. A clone without a sibling checkout cannot resolve a "
        f"path source.\n{FIX}")


def test_committed_lock_resolves_orca_core_from_the_registry():
    assert not lock_has_dev_source(_committed("uv.lock")), (
        f"uv.lock in HEAD resolves orca_core to a local checkout rather than "
        f"the registry.\n{FIX}")

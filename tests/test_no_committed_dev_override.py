"""No orca_core source override may reach a commit.

A ``[tool.uv.sources]`` path entry is a fact about one machine: committed, it
makes the project unresolvable everywhere else — ``uv lock`` fails outright on
a clone with no sibling orca_core. ``./dev`` never writes one, but a hand-made
entry is just as fatal.

These tests read the *committed* files, not the working tree.
"""

import re
import subprocess

import pytest

# Fallback for Python 3.10, which has no TOML parser. This project declares no
# other source, so the table header appearing at all is the entry.
SOURCE_TABLE = re.compile(r"^[ \t]*\[tool\.uv\.sources", re.MULTILINE)

FIX = ("Drop the entry and run against a local core with `./dev local`\n"
       "instead. A branch that needs unpublished orca_core is paired in CI — "
       "see .github/workflows/test.yml.")


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


def _has_orca_core_source(pyproject: str) -> bool:
    """True when pyproject.toml carries an orca_core source entry.

    TOML spells the same table several ways — a dotted header, a quoted key,
    an indented one — so parse it rather than matching one shape.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        return bool(SOURCE_TABLE.search(pyproject))
    try:
        parsed = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError:
        return bool(SOURCE_TABLE.search(pyproject))
    sources = parsed.get("tool", {}).get("uv", {}).get("sources", {})
    return any(key.replace("_", "-") == "orca-core" for key in sources)


def _locked_orca_core_source(lock: str) -> str:
    """The `source = { ... }` kind recorded for orca_core, '' when absent."""
    for block in lock.split("[[package]]"):
        if re.search(r'^name = "orca[-_]core"$', block, re.MULTILINE):
            match = re.search(r"^source = \{ (\w+)", block, re.MULTILINE)
            return match.group(1) if match else "an unreadable source"
    return ""


def test_committed_pyproject_has_no_orca_core_source():
    assert not _has_orca_core_source(_committed("pyproject.toml")), (
        f"pyproject.toml in HEAD carries a [tool.uv.sources] entry for "
        f"orca_core. A clone without a sibling checkout cannot resolve a "
        f"path source.\n{FIX}")


def test_committed_lock_resolves_orca_core_from_the_registry():
    source = _locked_orca_core_source(_committed("uv.lock"))
    assert source, "uv.lock in HEAD has no orca_core entry at all."
    assert source == "registry", (
        f"uv.lock in HEAD resolves orca_core from {source}, not the "
        f"registry.\n{FIX}")

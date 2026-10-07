"""Dev mode must never reach a commit.

Pointing this checkout at an orca_core next to it needs a ``[tool.uv.sources]``
entry, because uv has no local-only override file. That entry is a fact about
one machine: committed, it makes the project unresolvable everywhere else —
``uv lock`` fails outright on a clone with no sibling orca_core.

These tests read the *committed* files, not the working tree, so they pass
while you are pointed at a local checkout and fail only once that reaches a
commit.
"""

import re
import subprocess

import pytest

# Fallback for Python 3.10, which has no TOML parser. This project declares no
# other source, so the table header appearing at all is the entry.
SOURCE_TABLE = re.compile(r"^[ \t]*\[tool\.uv\.sources", re.MULTILINE)

FIX = ("Keep the override in your working tree, out of the commit:\n"
       "    git restore --staged pyproject.toml uv.lock\n"
       "A branch that needs unpublished orca_core is paired in CI instead — "
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


class TestLeavingDevModeKeepsThePin:
    """`orca-dev release` re-adds the orca-core requirement. Where it gets that
    requirement from decides whether leaving dev mode is lossless."""

    def test_the_spec_is_the_one_the_project_declares(self):
        """Not a copy. A constant here named 0.4.x long after the project moved
        to 0.5, so leaving dev mode walked the requirement two minors back and
        installed a core the console no longer supported."""
        import re
        from pathlib import Path

        from orca_ui.core_source import released_core_spec

        declared = re.search(r"""["'](orca[-_]core[^"']*)["']""",
                             Path("pyproject.toml").read_text())
        assert declared, "pyproject.toml declares no orca-core requirement"
        assert released_core_spec() == declared.group(1)

    def test_no_exact_core_version_is_hardcoded_in_the_tooling(self):
        """Any literal pin here is a second copy waiting to go stale."""
        import re
        from pathlib import Path

        source = Path("orca_ui/core_source.py").read_text()
        pins = re.findall(r"orca[-_]core\s*[<>=!]+\s*\d+\.\d+\.\d+", source)
        assert pins == [], f"hardcoded core pins in core_source.py: {pins}"

    def test_the_fallback_does_not_narrow_anything(self):
        """When the committed file cannot be read, the answer must not be a
        guess at the pin -- a wide spec lets the resolver do its job."""
        from orca_ui.core_source import CORE_RELEASE_SPEC_FALLBACK

        assert not re.search(r">=\s*\d+\.\d+\.\d+", CORE_RELEASE_SPEC_FALLBACK)

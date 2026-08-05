"""Which orca_core is installed, read from its PEP 610 record."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError

import pytest

from orca_ui import core_source
from orca_ui.core_source import CoreSource, resolve


class FakeDist:
    """Stands in for the installed distribution: a version and the
    direct_url.json an index install would not have at all."""

    def __init__(self, version="0.4.0", direct_url=None):
        self.version = version
        self._direct_url = direct_url

    def read_text(self, name):
        if name == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


@pytest.fixture
def installed(monkeypatch):
    def install(dist):
        monkeypatch.setattr(
            core_source.Distribution, "from_name", staticmethod(lambda name: dist)
        )
    return install


def test_index_install_is_a_release(installed):
    """No direct_url.json is the marker of an ordinary wheel from an index."""
    installed(FakeDist())
    source = resolve()
    assert source.kind == "released"
    assert source.is_development is False
    assert source.version == "0.4.0"


def test_editable_checkout_reports_path_branch_and_dirt(installed, monkeypatch):
    installed(FakeDist(direct_url={
        "url": "file:///home/dev/orca/orca_core",
        "dir_info": {"editable": True},
    }))
    monkeypatch.setattr(
        core_source, "_git_state", lambda path: ("feature/wrist", True)
    )
    source = resolve()
    assert source.kind == "local"
    assert source.editable is True
    assert source.location == "/home/dev/orca/orca_core"
    assert (source.branch, source.dirty) == ("feature/wrist", True)
    assert source.is_development is True
    assert "feature/wrist" in source.summary()
    assert "modified" in source.summary()


def test_git_install_reports_the_requested_branch(installed):
    installed(FakeDist(direct_url={
        "url": "https://github.com/orcahand/orca_core.git",
        "vcs_info": {"vcs": "git", "commit_id": "abc123", "requested_revision": "main"},
    }))
    source = resolve()
    assert source.kind == "git"
    assert source.branch == "main"
    assert source.is_development is True


def test_url_encoded_checkout_path_is_decoded(installed, monkeypatch):
    installed(FakeDist(direct_url={
        "url": "file:///home/dev/my%20repos/orca_core",
        "dir_info": {"editable": True},
    }))
    monkeypatch.setattr(core_source, "_git_state", lambda path: (None, False))
    assert resolve().location == "/home/dev/my repos/orca_core"


def test_a_missing_orca_core_never_raises(monkeypatch):
    """resolve() runs on the UI startup path; it reports, it does not break."""
    def missing(name):
        raise PackageNotFoundError(name)
    monkeypatch.setattr(
        core_source.Distribution, "from_name", staticmethod(missing)
    )
    source = resolve()
    assert source.kind == "unknown"
    assert source.summary()


def test_unparseable_record_is_unknown_not_a_crash(installed):
    dist = FakeDist()
    dist.read_text = lambda name: "{not json"
    installed(dist)
    assert resolve().kind == "unknown"


def test_git_state_ignores_a_path_that_is_not_a_checkout():
    assert core_source._git_state("/nonexistent/path/xyz") == (None, False)
    assert core_source._git_state(None) == (None, False)


# ----- what crosses the wire -------------------------------------------------

def test_payload_never_leaks_the_developers_filesystem_path():
    """The UI can be bound past localhost; the checkout path is not shared."""
    source = CoreSource(
        version="0.4.0", kind="local", location="/home/dev/secret/orca_core",
        editable=True, branch="feature/x", dirty=False,
    )
    payload = source.as_dict()
    assert "/home/dev/secret" not in json.dumps(payload)
    assert payload["development"] is True
    assert payload["branch"] == "feature/x"


def test_released_payload_is_not_flagged_as_development():
    payload = CoreSource(version="0.4.0", kind="released").as_dict()
    assert payload["development"] is False


# ----- stripping dev mode out of a commit ------------------------------------

RELEASED_PYPROJECT = """\
[project]
name = "orca_ui"
version = "0.2.0"
dependencies = [
    "orca_core>=0.4,<0.5",
    "fastapi>=0.110",
]

[build-system]
requires = ["hatchling>=1.27.0"]
"""

DEV_PYPROJECT = """\
[project]
name = "orca_ui"
version = "0.2.0"
dependencies = [
    "orca_core>=0.4,<0.5",
    "fastapi>=0.110",
]

[build-system]
requires = ["hatchling>=1.27.0"]

[tool.uv.sources]
orca-core = { path = "../orca_core", editable = true }
"""


def test_stripping_a_dev_override_restores_the_released_file_exactly():
    """The whole guard rests on this: strip(dev) must equal the released
    file byte for byte, or every commit would carry a stray diff."""
    assert core_source.strip_dev_override(DEV_PYPROJECT) == RELEASED_PYPROJECT


def test_stripping_keeps_other_entries_under_the_sources_table():
    text = DEV_PYPROJECT.replace(
        "orca-core = { path = \"../orca_core\", editable = true }",
        "orca-core = { path = \"../orca_core\", editable = true }\n"
        "other-pkg = { path = \"../other\" }",
    )
    stripped = core_source.strip_dev_override(text)
    assert "other-pkg" in stripped
    assert "[tool.uv.sources]" in stripped
    assert "orca-core = {" not in stripped


def test_stripping_a_released_file_changes_nothing():
    assert core_source.strip_dev_override(RELEASED_PYPROJECT) == RELEASED_PYPROJECT


def test_stripping_a_table_mid_file_restores_it_exactly():
    """uv appends the table, but a hand-edited file can carry it anywhere."""
    released = RELEASED_PYPROJECT + '\n[tool.hatch.build]\npackages = ["orca_ui"]\n'
    dev = (
        RELEASED_PYPROJECT
        + '\n[tool.uv.sources]\norca-core = { path = "../orca_core", editable = true }\n'
        + '\n[tool.hatch.build]\npackages = ["orca_ui"]\n'
    )
    assert core_source.strip_dev_override(dev) == released


def test_override_on_a_final_line_without_a_newline_is_still_stripped():
    """`git show` can hand back content whose last line has no newline; an
    override there must not slip through as "not dev mode"."""
    text = DEV_PYPROJECT.rstrip("\n")
    assert core_source.has_dev_override(text) is True
    assert "[tool.uv.sources]" not in core_source.strip_dev_override(text)


def test_reading_a_staged_file_preserves_its_trailing_newline(tmp_path, monkeypatch):
    """Content read for rewriting must be verbatim — a stripped newline would
    be silently committed as a whitespace change."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)
    run("git", "init", "-q", ".")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "T")
    (repo / "pyproject.toml").write_text(RELEASED_PYPROJECT)
    run("git", "add", "-A")

    monkeypatch.chdir(repo)
    assert core_source._staged("pyproject.toml") == RELEASED_PYPROJECT


@pytest.mark.parametrize("name", ["orca-core", "orca_core"])
def test_override_is_detected_under_either_spelling(name):
    text = f'[tool.uv.sources]\n{name} = {{ path = "../orca_core" }}\n'
    assert core_source.has_dev_override(text) is True


def test_a_git_branch_override_is_detected_too():
    text = ('[tool.uv.sources]\norca-core = { git = '
            '"https://github.com/orcahand/orca_core.git", branch = "x" }\n')
    assert core_source.has_dev_override(text) is True
    assert "[tool.uv.sources]" not in core_source.strip_dev_override(text)


LOCK_RELEASED = """\
[[package]]
name = "orca-core"
version = "0.4.0"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_EDITABLE = """\
[[package]]
name = "orca-core"
version = "0.4.0"
source = { editable = "../orca_core" }
"""


def test_lockfile_dev_source_is_recognised():
    assert core_source.lock_has_dev_source(LOCK_EDITABLE) is True
    assert core_source.lock_has_dev_source(LOCK_RELEASED) is False


def test_lockfile_without_orca_core_is_not_dev():
    assert core_source.lock_has_dev_source('[[package]]\nname = "fastapi"\n') is False


def test_only_orca_cores_source_is_consulted():
    """Another package installed from a path must not read as dev mode."""
    text = (
        '[[package]]\nname = "some-tool"\nsource = { editable = "../tool" }\n'
        + LOCK_RELEASED
    )
    assert core_source.lock_has_dev_source(text) is False

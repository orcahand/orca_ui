"""Report which ``orca_core`` this process is running against.

The console depends on the published ``orca_core``, which is what a plain
``uv run`` installs. ``./dev local`` puts a checkout ahead of it on
``sys.path`` — and whoever is holding the hand then needs to see, at a glance,
that it is not a released build.

:func:`resolve` answers that from where ``orca_core`` imports from, falling back
to the installed distribution's PEP 610 record.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import Distribution, PackageNotFoundError
from typing import Optional

CORE_PACKAGE = "orca_core"
SHIM_DIR = "orca-core-dev"
"""Directory inside ``.venv`` where ``./dev local`` links the checkout. Keep
in sync with ``dev``."""

_GIT_TIMEOUT_S = 5
"""Cap on the git calls describing a local checkout: this runs on the UI's
startup path, where a hung git must never hold up the server."""


@dataclass(frozen=True)
class CoreSource:
    """Where the imported ``orca_core`` came from.

    ``kind`` is ``"released"`` for an ordinary index install, ``"local"`` for
    a directory (the editable dev setup), ``"git"`` for a VCS install, and
    ``"unknown"`` when the record cannot be read.
    """

    version: str
    kind: str
    location: Optional[str] = None
    editable: bool = False
    branch: Optional[str] = None
    dirty: bool = False

    @property
    def is_development(self) -> bool:
        """True when this is not a released build, so callers can flag it."""
        return self.kind in ("local", "git")

    def summary(self, with_location: bool = True) -> str:
        """One line, for a startup banner or a status pill.

        ``with_location=False`` drops the checkout path, for text that leaves
        this machine.
        """
        if self.kind == "local":
            detail = "local"
            if with_location and self.location:
                detail += f" {_display_path(self.location)}"
            if self.branch:
                detail += f" @ {self.branch}"
            if self.dirty:
                detail += " (modified)"
        elif self.kind == "git":
            detail = f"git {self.branch or (self.location if with_location else None) or '?'}"
        elif self.kind == "released":
            detail = "released"
        else:
            detail = "source unknown"
        return f"{CORE_PACKAGE} {self.version} — {detail}"

    def as_dict(self) -> dict:
        # No ``location``: this crosses HTTP, and the UI can be bound wider
        # than localhost. The path is a developer's home directory.
        return {
            "version": self.version,
            "kind": self.kind,
            "branch": self.branch,
            "dirty": self.dirty,
            "development": self.is_development,
            "summary": self.summary(with_location=False),
        }


def resolve() -> CoreSource:
    """Describe the ``orca_core`` an import would load. Never raises: an
    unreadable install is reported as ``kind="unknown"`` rather than breaking a
    caller that only wanted a banner line."""
    shimmed = _shimmed_checkout()
    if shimmed:
        branch, dirty = _git_state(shimmed)
        return CoreSource(version=_checkout_version(shimmed), kind="local",
                          location=shimmed, editable=True,
                          branch=branch, dirty=dirty)
    try:
        dist = Distribution.from_name(CORE_PACKAGE)
        version = dist.version
    except PackageNotFoundError:
        return CoreSource(version="not installed", kind="unknown")
    except Exception:
        return CoreSource(version="?", kind="unknown")

    try:
        raw = dist.read_text("direct_url.json")
    except Exception:
        raw = None

    # No direct_url.json means the wheel came from an index — a release.
    if not raw:
        return CoreSource(version=version, kind="released")

    try:
        record = json.loads(raw)
    except ValueError:
        return CoreSource(version=version, kind="unknown")

    url = record.get("url", "")
    if "vcs_info" in record:
        vcs = record["vcs_info"]
        return CoreSource(
            version=version,
            kind="git",
            location=url,
            branch=vcs.get("requested_revision") or vcs.get("commit_id"),
        )

    if "dir_info" in record:
        path = _path_from_file_url(url)
        branch, dirty = _git_state(path)
        return CoreSource(
            version=version,
            kind="local",
            location=path,
            editable=bool(record["dir_info"].get("editable")),
            branch=branch,
            dirty=dirty,
        )

    return CoreSource(version=version, kind="unknown", location=url or None)


@lru_cache(maxsize=1)
def resolve_cached() -> CoreSource:
    """:func:`resolve` for hot paths (banner, API responses).

    The answer is fixed for the life of the process: switching branches under
    an editable install does not reload the modules already imported, so the
    startup reading is the one that describes the running code.
    """
    return resolve()


def _shimmed_checkout() -> Optional[str]:
    """The checkout ``./dev local`` put ahead of the installed package, if any.

    The shim only moves ``sys.path``, so the installed distribution's metadata
    still describes the release; where the module file lives is the truth.
    """
    try:
        spec = importlib.util.find_spec(CORE_PACKAGE)
    except Exception:
        return None
    if not spec or not spec.origin:
        return None
    package_dir = os.path.dirname(spec.origin)
    if os.path.basename(os.path.dirname(package_dir)) != SHIM_DIR:
        return None
    return os.path.dirname(os.path.realpath(package_dir))


def _checkout_version(path: str) -> str:
    try:
        with open(os.path.join(path, "pyproject.toml")) as fh:
            match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(),
                              re.MULTILINE)
    except OSError:
        return "?"
    return match.group(1) if match else "?"


def _path_from_file_url(url: str) -> Optional[str]:
    if not url.startswith("file://"):
        return url or None
    from urllib.parse import unquote, urlparse

    return unquote(urlparse(url).path) or None


def _display_path(path: str) -> str:
    """Shorten a checkout path for a one-line summary."""
    try:
        relative = os.path.relpath(path)
    except ValueError:  # different drive on Windows
        return path
    return relative if len(relative) < len(path) else path


def _git(*args: str, cwd: Optional[str] = None,
         strip: bool = True) -> Optional[str]:
    """Run git and return stdout, or ``None`` if it failed or is unavailable.

    ``strip=False`` returns stdout verbatim — required when reading file
    contents, where a stripped trailing newline would corrupt what gets
    written back.
    """
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() if strip else done.stdout


def _git_state(path: Optional[str]) -> "tuple[Optional[str], bool]":
    """Branch name and dirty flag for a checkout, or ``(None, False)`` when
    the path is not a usable git repository."""
    if not path or not os.path.isdir(path):
        return None, False
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=path)
    if branch == "HEAD":  # detached
        branch = _git("rev-parse", "--short", "HEAD", cwd=path)
    status = _git("status", "--porcelain", cwd=path)
    return branch or None, bool(status)

"""Report and switch which ``orca_core`` this checkout runs against.

The console depends on the published ``orca_core``, which is what a plain
clone installs. Anyone working on both repos at once points it at a local
checkout instead — and then needs to be able to tell, at a glance, that they
are no longer on a released build.

:func:`resolve` answers "which one is live?" by reading the installed
distribution's PEP 610 record; the ``orca-dev`` command wraps ``uv add`` to
move between them, so pyproject.toml, uv.lock and the virtualenv are never
left disagreeing.

uv has no local-only override file — ``[tool.uv.sources]`` must live in the
tracked pyproject.toml — so dev mode necessarily edits a tracked file. The
pre-commit half of this module removes it from what gets committed, keeping
the working tree in dev mode: see :func:`precommit_fix`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import Distribution, PackageNotFoundError
from typing import List, Optional

CORE_PACKAGE = "orca_core"
CORE_REPO = "https://github.com/orcahand/orca_core.git"
CORE_RELEASE_SPEC = "orca_core>=0.4,<0.5"
SIBLING_PATH = "../orca_core"

SETTINGS_FILE = ".orca-dev.json"
"""Remembers an unusual checkout location. Gitignored: it is a fact about
this machine, not about the project."""

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
    """Describe the installed ``orca_core``. Never raises: an unreadable
    install is reported as ``kind="unknown"`` rather than breaking a caller
    that only wanted a banner line."""
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


# ---------------------------------------------------------------------------
# Finding the local orca_core checkout
# ---------------------------------------------------------------------------


def _project_root() -> str:
    """The orca_ui checkout containing the pyproject.toml ``uv add`` edits."""
    here = os.path.abspath(os.getcwd())
    while True:
        if os.path.isfile(os.path.join(here, "pyproject.toml")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise SystemExit(
                "No pyproject.toml found above the current directory — run this "
                "from inside the orca_ui checkout."
            )
        here = parent


def _settings_path() -> str:
    return os.path.join(_project_root(), SETTINGS_FILE)


def _remembered_path() -> Optional[str]:
    try:
        with open(_settings_path()) as fh:
            path = json.load(fh).get("core_path")
    except (OSError, ValueError):
        return None
    return path if path and _is_core_checkout(path) else None


def _remember_path(path: str) -> None:
    try:
        with open(_settings_path(), "w") as fh:
            json.dump({"core_path": path}, fh, indent=2)
            fh.write("\n")
    except OSError:
        pass  # Remembering is a convenience; failing to is not an error.


def _is_core_checkout(path: str) -> bool:
    """True when ``path`` is an orca_core source tree (and not, say, a
    sibling repo that merely has the name in its directory)."""
    pyproject = os.path.join(path, "pyproject.toml")
    try:
        with open(pyproject) as fh:
            head = fh.read(4000)
    except OSError:
        return False
    return bool(re.search(r'^name\s*=\s*"orca[-_]core"', head, re.MULTILINE))


def _candidate_checkouts() -> List[str]:
    """Every orca_core source tree sitting beside the orca_ui checkout.

    Several is normal — worktrees and experiment clones live side by side —
    so this only ever offers a list; it never silently picks among them.
    """
    parent = os.path.dirname(_project_root())
    try:
        entries = sorted(os.listdir(parent))
    except OSError:
        return []
    found = []
    for entry in entries:
        path = os.path.join(parent, entry)
        if os.path.isdir(path) and _is_core_checkout(path):
            found.append(path)
    return found


def find_local_checkout(explicit: Optional[str] = None,
                        interactive: bool = True) -> str:
    """Locate the orca_core checkout to develop against.

    Tries, in order: an explicit path, the one remembered for this machine,
    the ``../orca_core`` sibling, then a scan of neighbouring directories.
    Asks only when that leaves a genuine ambiguity, and remembers the answer.
    """
    if explicit:
        path = os.path.abspath(explicit)
        if not _is_core_checkout(path):
            raise SystemExit(
                f"{path} is not an orca_core checkout (no pyproject.toml "
                f"naming orca_core)."
            )
        _remember_path(path)
        return path

    remembered = _remembered_path()
    if remembered:
        return remembered

    sibling = os.path.abspath(os.path.join(_project_root(), SIBLING_PATH))
    if _is_core_checkout(sibling):
        return sibling

    candidates = _candidate_checkouts()
    if len(candidates) == 1:
        _remember_path(candidates[0])
        return candidates[0]

    if not interactive or not sys.stdin.isatty():
        raise SystemExit(
            "Could not find an orca_core checkout automatically. Pass one:\n"
            "    uv run orca-dev local /path/to/orca_core"
        )

    chosen = _prompt_for_checkout(candidates)
    _remember_path(chosen)
    return chosen


def _prompt_for_checkout(candidates: List[str]) -> str:
    if candidates:
        print("Several orca_core checkouts are available:\n")
        for index, path in enumerate(candidates, start=1):
            branch, dirty = _git_state(path)
            marks = f"  [{branch}{' *' if dirty else ''}]" if branch else ""
            print(f"  {index}) {_display_path(path)}{marks}")
        print()
        answer = input("Which one? (number, or a path): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
    else:
        print("No orca_core checkout found next to this repository.")
        answer = input("Path to your orca_core checkout: ").strip()

    path = os.path.abspath(os.path.expanduser(answer))
    if not _is_core_checkout(path):
        raise SystemExit(f"{path} is not an orca_core checkout.")
    return path


# ---------------------------------------------------------------------------
# Switching
# ---------------------------------------------------------------------------


def _run_uv(*args: str, required: bool = True) -> None:
    """Run a uv subcommand against the project root.

    ``required=False`` tolerates a non-zero exit, for the ``uv remove`` that
    clears an existing source entry: nothing to remove is a fine outcome, and
    aborting there would leave the project with no orca_core at all.
    """
    root = _project_root()
    print(f"$ uv {' '.join(args)}")
    try:
        done = subprocess.run(["uv", *args], cwd=root)
    except FileNotFoundError:
        raise SystemExit("uv is not installed — see https://docs.astral.sh/uv/")
    if done.returncode != 0 and required:
        raise SystemExit(done.returncode)


def _ensure_hooks_enabled() -> None:
    """Point git at .githooks the first time dev mode is turned on.

    The pre-commit hook is what keeps the override out of commits, so dev
    mode should not be possible without it.
    """
    root = _project_root()
    if not os.path.isdir(os.path.join(root, ".githooks")):
        return
    current = _git("config", "core.hooksPath", cwd=root)
    if current == ".githooks":
        return
    if current:
        print(f"Note: core.hooksPath is {current!r}, not '.githooks'. The "
              f"commit guard that strips dev mode lives in .githooks/pre-commit.")
        return
    _git("config", "core.hooksPath", ".githooks", cwd=root)
    print("Enabled .githooks (keeps dev mode out of your commits).")


def use_local(path: Optional[str] = None) -> None:
    checkout = find_local_checkout(path)
    _ensure_hooks_enabled()
    # uv records the path verbatim and runs from the project root, so hand it
    # one relative to that root — otherwise pyproject.toml ends up with a path
    # relative to wherever this happened to be invoked.
    _run_uv("add", "--editable", os.path.relpath(checkout, _project_root()))


def use_branch(name: str) -> None:
    _ensure_hooks_enabled()
    # Drop any existing source entry first: `uv add` alone keeps a path source
    # in place, which would silently outrank the branch.
    _run_uv("remove", CORE_PACKAGE, required=False)
    _run_uv("add", f"{CORE_PACKAGE} @ git+{CORE_REPO}", "--branch", name)


def use_release() -> None:
    _run_uv("remove", CORE_PACKAGE, required=False)
    _run_uv("add", CORE_RELEASE_SPEC)


# ---------------------------------------------------------------------------
# Keeping dev mode out of commits
# ---------------------------------------------------------------------------

# The trailing newline is optional: the entry is the last line of the file
# whenever uv appended the table, and may arrive without one.
_SOURCE_ENTRY = re.compile(r"^orca[-_]core\s*=\s*\{[^\n]*\}[ \t]*(?:\n|\Z)",
                           re.MULTILINE)
_EMPTY_SOURCES_TABLE = re.compile(r"\n?^\[tool\.uv\.sources\][ \t]*\n(?=\s*(\[|\Z))",
                                  re.MULTILINE)

PYPROJECT = "pyproject.toml"
LOCKFILE = "uv.lock"


def strip_dev_override(text: str) -> str:
    """Return ``pyproject.toml`` content with the orca_core source entry gone,
    dropping the ``[tool.uv.sources]`` header if nothing else is under it."""
    out = _SOURCE_ENTRY.sub("", text)
    out = _EMPTY_SOURCES_TABLE.sub("\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # Removing a trailing table leaves a blank line at EOF; a commit that
    # differs from the released file by whitespace defeats the whole point.
    if text.endswith("\n"):
        out = out.rstrip("\n") + "\n"
    return out


def has_dev_override(text: str) -> bool:
    return bool(_SOURCE_ENTRY.search(text))


def lock_has_dev_source(text: str) -> bool:
    """True when uv.lock resolves orca_core to anything but a registry."""
    for block in text.split("[[package]]"):
        if re.search(r'^name = "orca[-_]core"$', block, re.MULTILINE):
            match = re.search(r"^source = \{ (\w+)", block, re.MULTILINE)
            return bool(match and match.group(1) != "registry")
    return False


def _dependency_block(text: str) -> str:
    match = re.search(r"^dependencies = \[.*?^\]", text, re.MULTILINE | re.DOTALL)
    return match.group(0) if match else ""


def _staged(path: str) -> Optional[str]:
    return _git("show", f":{path}", strip=False)


def _committed(path: str) -> Optional[str]:
    return _git("show", f"HEAD:{path}", strip=False)


def _restage(path: str, content: str) -> None:
    """Replace ``path`` in the index without touching the working tree."""
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--path", path, "--stdin"],
        input=content, text=True, capture_output=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--cacheinfo", f"100644,{blob},{path}"], check=True
    )


def precommit_fix() -> int:
    """Strip dev mode from what is about to be committed.

    The working tree is left alone — you stay in dev mode, and only the
    commit is clean. Returns a shell exit code; never blocks the commit.
    """
    fixed = []

    staged_pyproject = _staged(PYPROJECT)
    if staged_pyproject and has_dev_override(staged_pyproject):
        stripped = strip_dev_override(staged_pyproject)
        committed = _committed(PYPROJECT)
        if committed is not None and stripped == committed:
            _git("restore", "--staged", PYPROJECT)
        else:
            _restage(PYPROJECT, stripped)
        fixed.append(PYPROJECT)

    staged_lock = _staged(LOCKFILE)
    if staged_lock and lock_has_dev_source(staged_lock):
        # The lock cannot be rewritten here (resolving needs the network), so
        # the committed one stays as it was: correct for the released package.
        if _committed(LOCKFILE) is not None:
            _git("restore", "--staged", LOCKFILE)
            fixed.append(LOCKFILE)

    if not fixed:
        return 0

    print(f"orca-dev: committing without your local orca_core override "
          f"({', '.join(fixed)}). Your working tree stays in dev mode.")

    # The one case the index fix cannot cover: a dependency edit made while in
    # dev mode needs a re-resolved lock, which only `uv lock` can produce.
    new_pyproject = _staged(PYPROJECT) or ""
    old_pyproject = _committed(PYPROJECT) or ""
    if _dependency_block(new_pyproject) != _dependency_block(old_pyproject):
        print("orca-dev: WARNING — dependencies changed. uv.lock was kept at "
              "its committed state and is now stale. Before pushing, run:\n"
              "    uv run orca-dev release && uv lock && git add uv.lock\n"
              "    git commit --amend --no-edit && uv run orca-dev local")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_status(source: Optional[CoreSource] = None) -> CoreSource:
    source = source or resolve()
    print(f"{CORE_PACKAGE:<12}{source.version}")
    if source.kind == "local":
        kind = "local checkout (live)" if source.editable else "local checkout"
        print(f"{'source':<12}{kind}")
        print(f"{'path':<12}{source.location}")
        if source.branch:
            state = " (uncommitted changes)" if source.dirty else ""
            print(f"{'branch':<12}{source.branch}{state}")
    elif source.kind == "git":
        print(f"{'source':<12}git branch")
        print(f"{'url':<12}{source.location}")
        print(f"{'ref':<12}{source.branch}")
    elif source.kind == "released":
        print(f"{'source':<12}released package (PyPI)")
    else:
        print(f"{'source':<12}could not be determined")
    return source


def _confirm(question: str, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def _interactive_default() -> None:
    """``orca-dev`` with no arguments: report, then offer the obvious move."""
    source = _print_status()
    print()

    if source.is_development:
        print("You are on a development build. Commits are unaffected — the "
              "pre-commit hook keeps this setup out of them.")
        print("`orca-dev release` returns to the published package.")
        return

    try:
        checkout = find_local_checkout()
    except SystemExit as e:
        print(e)
        return

    branch, dirty = _git_state(checkout)
    where = _display_path(checkout)
    detail = f" (branch {branch}{', modified' if dirty else ''})" if branch else ""
    print(f"Found an orca_core checkout at {where}{detail}.")
    if _confirm("Develop against it?"):
        use_local(checkout)
        print()
        _print_status()


def main(argv=None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="orca-dev",
        description="Show or switch the orca_core this checkout runs against. "
                    "With no arguments: report, and offer to use your local "
                    "checkout.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="Show which orca_core is installed.")

    local = sub.add_parser(
        "local", help="Develop against a local checkout (found automatically).")
    local.add_argument("path", nargs="?", default=None,
                       help="Only needed the first time, and only if the "
                            "checkout is somewhere unusual.")

    branch = sub.add_parser(
        "branch", help="Track a branch of the orca_core repo (no checkout needed).")
    branch.add_argument("name")

    sub.add_parser("release", help="Use the published orca_core from PyPI.")
    sub.add_parser("_precommit", help=argparse.SUPPRESS)

    args = parser.parse_args(argv)

    if args.command is None:
        _interactive_default()
        return
    if args.command == "status":
        _print_status()
        return
    if args.command == "_precommit":
        raise SystemExit(precommit_fix())

    if args.command == "local":
        use_local(args.path)
    elif args.command == "branch":
        use_branch(args.name)
    elif args.command == "release":
        use_release()

    print()
    _print_status()


if __name__ == "__main__":
    main()

"""Where the orca_teleop checkout lives, and how that answer is remembered.

orca_teleop is not a dependency — it is a sibling checkout the console shells
into (see ``runner.py``). The default location follows the same sibling
convention as ``orca_core = {path = "../orca_core"}``, but the user may install
it anywhere, so the chosen path is written to a per-machine memo file that
``resolve_command`` consults on every probe.

Kept separate from ``runner.py`` so the installer and the runner can share it
without either importing the other.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

TELEOP_DIR_NAME = "orca_teleop"
DESCRIPTION_DIR_NAME = "orcahand_description"

SETTINGS_FILE = ".orca-ui.json"
"""Remembers an unusual checkout location. Gitignored: it is a fact about this
machine, not about the project. Mirrors ``core_source.SETTINGS_FILE``."""

TELEOP_PATH_KEY = "teleop_path"

_memo_lock = threading.Lock()
_memo_cache: tuple[str, float, dict] | None = None


def project_root() -> str | None:
    """The orca_ui checkout this package was installed from, or None for an
    ordinary wheel install.

    Anchored on the package directory, NOT the cwd: a server's cwd is
    arbitrary. (``core_source._project_root`` walks up from the cwd and raises
    ``SystemExit`` — neither is acceptable on a request path.)
    """
    import orca_ui

    current = os.path.dirname(os.path.dirname(os.path.abspath(orca_ui.__file__)))
    for _ in range(4):
        candidate = os.path.join(current, "pyproject.toml")
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as f:
                    if "orca" in f.read(4096):
                        return current
            except OSError:
                return None
            return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def settings_path() -> str:
    """Where the memo lives: the checkout root when there is one, else a
    per-user directory (same fallback as the pose library)."""
    root = project_root()
    if root:
        return os.path.join(root, SETTINGS_FILE)
    home = Path.home() / ".orca_ui"
    return str(home / SETTINGS_FILE)


def _read_settings() -> dict:
    """Memo contents, cached on (path, mtime).

    ``resolve_command`` runs on every state publish, so this must not open a
    file per frame.
    """
    global _memo_cache
    path = settings_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _memo_lock:
        if _memo_cache and _memo_cache[0] == path and _memo_cache[1] == mtime:
            return _memo_cache[2]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    with _memo_lock:
        _memo_cache = (path, mtime, data)
    return data


def remember_teleop_dir(path: str) -> None:
    """Record the checkout location. Read-modify-write: the file is shared
    with any other key we later keep here. Failing to remember is not an
    error — the sibling scan still finds a default install."""
    global _memo_cache
    target = settings_path()
    data = dict(_read_settings())
    data[TELEOP_PATH_KEY] = path
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        return
    with _memo_lock:
        _memo_cache = None


def remembered_teleop_dir() -> str | None:
    """The remembered checkout, or None when there is none or it has since
    been deleted (a stale memo must fall through to the sibling scan)."""
    path = _read_settings().get(TELEOP_PATH_KEY)
    if not isinstance(path, str) or not path:
        return None
    return path if os.path.isdir(path) else None


def sibling_root() -> str:
    """Directory the sibling checkouts live in — the orca_ui checkout's parent,
    or the home directory for a wheel install."""
    root = project_root()
    return os.path.dirname(root) if root else str(Path.home())


def default_install_dir() -> str:
    """Where Install proposes to put the checkout."""
    return os.path.join(sibling_root(), TELEOP_DIR_NAME)


def default_description_dir() -> str:
    """Sibling orcahand_description — the retargeter's URDF source."""
    return os.path.join(sibling_root(), DESCRIPTION_DIR_NAME)

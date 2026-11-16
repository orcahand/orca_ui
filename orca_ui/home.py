"""Where the console keeps its own state: ``<ORCA_HOME>/ui``, default ``~/.orca/ui``.

It holds the pose library (recordings included), the assembly progress and the
browser profile. Physical hands live beside it, in orca_core's
``<ORCA_HOME>/hands/``. Consoles up to 0.5 kept their state in ``~/.orca_ui``;
:func:`prepare_ui_home` renames that folder here once, on startup, and keeps
using it where it is whenever a rename is not possible.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_in_use: Path | None = None


def orca_home() -> Path:
    value = os.environ.get("ORCA_HOME")
    return Path(value).expanduser().absolute() if value else Path.home() / ".orca"


def _custom_orca_home() -> bool:
    """ORCA_HOME is set to something other than the default ``~/.orca``."""
    return orca_home() != Path.home() / ".orca"


def legacy_ui_home() -> Path:
    return Path.home() / ".orca_ui"


def ui_home() -> Path:
    """The folder this console reads and writes its own state in."""
    return _in_use or orca_home() / "ui"


def prepare_ui_home(library_dir: str | None = None) -> str | None:
    """Move ``~/.orca_ui`` into place if needed and fix :func:`ui_home` for this run.

    With ``ORCA_HOME`` set elsewhere than ``~/.orca`` nothing is moved: a scratch
    ORCA_HOME must not take the operator's library with it. Returns a line for
    the startup banner when a move happened.
    """
    global _in_use
    source, target = legacy_ui_home(), orca_home() / "ui"
    if _custom_orca_home():
        if source.exists() and not _points_at(source, target):
            logger.warning("ORCA_HOME is set, so %s was not moved and is not read; "
                           "this console keeps its state in %s", source, target)
        _in_use = target
        return None
    _in_use, moved = move_legacy_ui_home(source, target, library_dir)
    return f"moved {source} to {target}" if moved else None


def _inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def _points_at(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.resolve() == target.resolve()


def _settled(source: Path, target: Path) -> tuple[Path, bool]:
    if source.exists() and not _points_at(source, target):
        logger.warning("%s is in use; %s was left as it is and is no longer read", target, source)
    return target, False


def move_legacy_ui_home(source: Path, target: Path,
                        library_dir: str | None = None) -> tuple[Path, bool]:
    """Rename the console's old state folder ``source`` to ``target``, once.

    Returns the folder to use for this run and whether a move happened. Only
    a rename is tried: when it fails the console keeps running from
    ``source``. After a rename ``source`` becomes a symlink to ``target``, so
    an older console still running, or a downgrade, finds its data.
    """
    if target.exists() or _points_at(source, target):
        return _settled(source, target)
    if not source.exists():
        return target, False
    if source.is_symlink():
        logger.warning("%s is a symlink; it was not moved and is still used", source)
        return source, False
    if library_dir and _inside(Path(library_dir), source):
        logger.warning("%s was not moved: --library-dir %s is inside it", source, library_dir)
        return source, False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
    except OSError as e:
        if target.exists():
            return _settled(source, target)  # another console moved it a moment ago
        logger.warning("could not move %s to %s (%s); still using it", source, target, e)
        return source, False

    if os.name == "posix":
        try:
            os.symlink(target.resolve(), source, target_is_directory=True)
        except OSError as e:
            logger.warning("moved %s to %s, but could not leave a link at the old path (%s)",
                           source, target, e)
    return target, True

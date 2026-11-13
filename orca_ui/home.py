"""Where the console keeps its own state: ``<ORCA_HOME>/ui``, default ``~/.orca/ui``.

It holds the pose library (recordings included), the assembly progress and the
browser profile. Physical hands live beside it, in orca_core's
``<ORCA_HOME>/hands/``. Consoles up to 0.5 kept their state in ``~/.orca_ui``;
:func:`prepare_ui_home` moves that folder here once, on startup, and never
deletes anything it has not first put safely in place.
"""

from __future__ import annotations

import errno
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_in_use: Path | None = None


def orca_home() -> Path:
    value = os.environ.get("ORCA_HOME")
    return Path(value).expanduser() if value else Path.home() / ".orca"


def legacy_ui_home() -> Path:
    return Path.home() / ".orca_ui"


def ui_home() -> Path:
    """The folder this console reads and writes its own state in."""
    return _in_use or orca_home() / "ui"


def prepare_ui_home(library_dir: str | None = None) -> str | None:
    """Move ``~/.orca_ui`` into place if needed and fix :func:`ui_home` for this run.

    Returns a line for the startup banner when a move happened.
    """
    global _in_use
    source, target = legacy_ui_home(), orca_home() / "ui"
    _in_use, moved = move_legacy_ui_home(source, target, library_dir)
    return f"moved {source} to {target}" if moved else None


def _inside(path: Path, folder: Path) -> bool:
    return path.expanduser().resolve().is_relative_to(folder.expanduser().resolve())


def _put_back(held: Path, source: Path) -> Path:
    """Return a source parked under ``held`` to its own name if that is free;
    returns where the source now is."""
    if not held.exists():
        return source
    if source.exists():
        logger.warning("console state is in both %s and %s; nothing was deleted", source, held)
        return source
    try:
        os.rename(held, source)
        return source
    except OSError as e:
        logger.warning("could not rename %s back to %s (%s); nothing was deleted", held, source, e)
        return held


def move_legacy_ui_home(source: Path, target: Path,
                        library_dir: str | None = None) -> tuple[Path, bool]:
    """Move the console's old state folder ``source`` to ``target``, once.

    Returns the folder to use for this run (``target``, or the source when it
    could not be moved) and whether a move happened. A rename where the
    filesystem allows it; across filesystems the source is parked under
    ``<source>.moving``, copied to ``<target>.moving``, renamed into place,
    and only then deleted. An interrupted move is resumed on the next start.
    """
    held = source.with_name(source.name + ".moving")
    staging = target.with_name(target.name + ".moving")

    if target.exists():
        for left in (source, held):
            if left.exists():
                logger.warning("%s is in use; %s was left as it is and is no longer read",
                               target, left)
        return target, False

    if staging.exists():
        if source.exists() or held.exists():
            shutil.rmtree(staging, ignore_errors=True)  # a copy of a source still in place
        else:
            logger.warning("%s holds an unfinished copy and no source remains; "
                           "it was left as it is", staging)

    origin = held if held.exists() else source if source.exists() else None
    if origin is None:
        return target, False
    if library_dir and _inside(Path(library_dir), origin):
        logger.warning("%s was not moved: --library-dir %s is inside it", origin, library_dir)
        return _put_back(held, source), False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(origin, target)
        return target, True
    except OSError as e:
        if target.exists() and not origin.exists():
            return target, False  # another console moved it a moment ago
        if e.errno != errno.EXDEV:
            logger.warning("could not move %s to %s (%s); still using it", origin, target, e)
            return _put_back(held, source), False

    if origin == source:
        try:
            os.rename(source, held)
        except OSError as e:
            logger.warning("could not move %s to %s (%s); still using it", source, target, e)
            return (target, False) if target.exists() else (source, False)
    try:
        shutil.copytree(held, staging, symlinks=True)
        os.rename(staging, target)
    except (OSError, shutil.Error) as e:
        logger.warning("could not copy %s to %s (%s); still using it", source, target, e)
        shutil.rmtree(staging, ignore_errors=True)
        return _put_back(held, source), False
    try:
        shutil.rmtree(held)
    except OSError as e:
        logger.warning("moved %s to %s, but could not delete %s (%s)", source, target, held, e)
    return target, True

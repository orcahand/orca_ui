"""The console's user-facing changelog: a Markdown document shipped in the
package and read at request time, so editing it needs no rebuild or restart.

Two lines per release are structural — the ``## UI <version> — <date>`` heading
and the ``Core:`` line naming the orca_core release to run with it. Everything
else is prose the reviewer writes.

"Don't show this again" is one indicator file in ``STATE_DIR``, named after the
release it dismisses. The directory is untracked, created on demand, and holds
nothing else: writing an indicator clears it first, so a release whose name no
longer matches leaves no residue and the folder never accumulates.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

CHANGELOG_PATH = Path(__file__).with_name("changelog.md")

# Beside the package, so a checkout keeps it out of git and an install keeps it
# out of the wheel. Only ever holds one indicator file.
STATE_DIR = Path(__file__).resolve().parent.parent / ".changelog"

_INDICATOR = re.compile(r"^ui-(\d+(?:\.\d+)*)\.seen$")

_ENTRY = re.compile(
    r"^##\s+(?:UI\s+)?v?(\d+(?:\.\d+)*)\s*(?:[—–-]+\s*(.*?))?\s*$", re.IGNORECASE
)
_CORE = re.compile(r"^Core:\s*v?(\d+(?:\.\d+)*)\s*$", re.IGNORECASE)


def _sort_key(entry_version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in entry_version.split("."))


def ui_version() -> str:
    try:
        return version("orca_ui")
    except PackageNotFoundError:
        return "0.0.0"


def read_markdown() -> str:
    try:
        return CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def entries(markdown: str | None = None) -> list[dict[str, str | None]]:
    """Every release in the document, newest version first."""
    text = read_markdown() if markdown is None else markdown
    found: list[dict[str, str | None]] = []
    for line in text.splitlines():
        heading = _ENTRY.match(line)
        if heading:
            found.append(
                {
                    "version": heading.group(1),
                    "date": (heading.group(2) or "").strip(),
                    "core": None,
                }
            )
            continue
        core = _CORE.match(line.strip())
        if core and found and found[-1]["core"] is None:
            found[-1]["core"] = core.group(1)
    return sorted(found, key=lambda e: _sort_key(str(e["version"])), reverse=True)


def latest_version(markdown: str | None = None) -> str | None:
    found = entries(markdown)
    return str(found[0]["version"]) if found else None


def seen_version() -> str | None:
    """The release whose notes were ticked away, read off the indicator file."""
    try:
        names = [entry.name for entry in STATE_DIR.iterdir() if entry.is_file()]
    except OSError:
        return None
    found = [m.group(1) for m in map(_INDICATOR.match, names) if m]
    # More than one means something else wrote here; treat it as undecided.
    return found[0] if len(found) == 1 else None


def _clear_state_dir() -> None:
    try:
        entries = list(STATE_DIR.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.is_file():
            try:
                entry.unlink()
            except OSError:
                pass


def set_seen(version: str | None) -> str | None:
    """Mark ``version`` dismissed, or clear the dismissal when given None.

    The directory is emptied either way, so exactly one indicator can exist.
    """
    _clear_state_dir()
    if version is None:
        return None
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"ui-{version}.seen").write_text(
            f"The console's {version} release notes have been dismissed.\n"
            "Delete this file to have them open again.\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    return version


def changelog() -> dict:
    """The payload the console reads: the document and what release it covers."""
    markdown = read_markdown()
    found = entries(markdown)
    latest = found[0] if found else None
    seen = seen_version()
    return {
        "ui_version": ui_version(),
        "latest_version": latest["version"] if latest else None,
        "recommended_core": latest["core"] if latest else None,
        "versions": [e["version"] for e in found],
        "dismissed": bool(latest) and seen == latest["version"],
        "markdown": markdown,
    }

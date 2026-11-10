"""Where a hardware-test session lives on disk, and how it is written.

Layout under the bench root (``~/orca_bench`` unless ``--bench-dir``)::

    <bench>/<label>/tests/
      sessions/<stamp> <plan>.json          the session index
      sessions/<stamp> <plan>.md            a summary for people and agents
      sessions/<stamp> <plan>.events.jsonl  every event of the session
      <feature>/<stamp>/result.json         that feature's step results
      <feature>/<stamp>/<step>/             check outputs, readings, screenshots

JSON files are written atomically (temp file + rename); jsonl files are
appended. Nothing here is ever deleted: results are kept for good.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

DEFAULT_BENCH = Path.home() / "orca_bench"
STAMP_FORMAT = "%Y-%m-%d_%H%M%S"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def bench_root(bench_dir: Optional[str]) -> Path:
    return Path(bench_dir).expanduser() if bench_dir else DEFAULT_BENCH


def stamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime(STAMP_FORMAT)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def safe_name(text: str) -> str:
    """``text`` as one path segment: letters, digits, ``_ . -`` only."""
    cleaned = _UNSAFE.sub("-", text.strip()).strip(".-")
    return cleaned[:80]


def default_label(serial: Optional[str], side: Optional[str], today: Optional[datetime] = None) -> str:
    """The board's provisioned serial, else ``unlabeled-<side>-<date>``."""
    if serial and safe_name(serial):
        return safe_name(serial)
    return f"unlabeled-{side or 'unknown'}-{(today or datetime.now()).strftime('%Y-%m-%d')}"


def display_path(path: Path | str) -> str:
    """``path`` with the home directory shown as ``~``."""
    text = str(path)
    home = str(Path.home())
    if text == home or text.startswith(home + os.sep):
        return "~" + text[len(home):]
    return text


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, json.dumps(data, indent=2, default=str) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, text)


def _write_atomic(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, default=str) + "\n")


def read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_jsonl(path: Path) -> list[dict]:
    """Every parseable line of ``path``; a torn last line is skipped."""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as file:
            for line in file:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


class SessionPaths:
    """Every path one session writes, from its bench root, label, plan and stamp."""

    def __init__(self, root: Path, label: str, plan_id: str, session_stamp: str):
        self.root = root
        self.label = label
        self.plan_id = plan_id
        self.stamp = session_stamp
        self.tests_dir = root / label / "tests"
        self.sessions_dir = self.tests_dir / "sessions"
        base = f"{session_stamp} {plan_id}"
        self.index_json = self.sessions_dir / f"{base}.json"
        self.index_md = self.sessions_dir / f"{base}.md"
        self.events = self.sessions_dir / f"{base}.events.jsonl"

    def feature_dir(self, feature_id: str) -> Path:
        return self.tests_dir / feature_id / self.stamp

    def feature_result(self, feature_id: str) -> Path:
        return self.feature_dir(feature_id) / "result.json"

    def step_dir(self, feature_id: str, step_id: str) -> Path:
        return self.feature_dir(feature_id) / safe_name(step_id)


def new_stamp(root: Path, label: str, plan_id: str) -> str:
    """A stamp no session for ``label`` uses yet (feature folders are shared
    between plans); a second session in the same second gets a ``-2`` suffix."""
    sessions_dir = SessionPaths(root, label, plan_id, "").sessions_dir
    base = stamp()
    candidate, n = base, 1
    while sessions_dir.is_dir() and any(sessions_dir.glob(f"{candidate} *.json")):
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def find_unfinished(root: Path, label: str, plan_id: str) -> Optional[str]:
    """Stamp of the newest unfinished session of ``plan_id`` for ``label``, if any."""
    sessions_dir = root / label / "tests" / "sessions"
    if not sessions_dir.is_dir():
        return None
    found: list[str] = []
    for path in sessions_dir.glob(f"* {plan_id}.json"):
        data = read_json(path)
        if isinstance(data, dict) and data.get("plan_id") == plan_id and not data.get("finished_at"):
            found.append(str(data.get("stamp") or path.name.split(" ", 1)[0]))
    return max(found) if found else None


def render_markdown(session: dict, rows: Iterable[dict]) -> str:
    """The session summary an agent or a person reads first.

    ``rows`` carry ``feature``, ``step``, ``title``, ``kind``, ``status``,
    ``note``, ``check`` (one-line summary) and ``folder``.
    """
    hand = session.get("hand") or {}
    sides = session.get("sides") or {}
    lines = [
        f"# {session.get('plan_title') or session.get('plan_id')}",
        "",
        f"- Session: `{session.get('id')}`",
        f"- Started: {session.get('started_at')}",
        f"- Finished: {session.get('finished_at') or 'not yet'}",
        f"- Hand: {hand.get('label')} — model {hand.get('model_name')}, side {hand.get('side')}, "
        f"motors {hand.get('motor_family')}, hardware version {hand.get('hardware_version')} "
        f"({hand.get('hardware_version_source') or 'unknown source'}), "
        f"capabilities {', '.join(hand.get('capabilities') or []) or 'none'}"
        + (" — MOCK" if hand.get("mock") else ""),
    ]
    for side in ("main", "branch"):
        info = sides.get(side) or {}
        state = f"orca_core {info.get('version')}" if info.get("available") else f"unavailable: {info.get('reason')}"
        lines.append(f"- {side} side: {state}")
    lines += [
        f"- Results: `{session.get('results_dir')}`",
        f"- Events: `{session.get('events_file')}`",
        "",
        "| Feature | Step | Kind | Status | Note | Check | Folder |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = [
            row["feature"],
            f"{row['step']} {row['title']}",
            row["kind"],
            row["status"],
            row.get("note") or "",
            row.get("check") or "",
            f"`{row['folder']}`",
        ]
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    lines.append("")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")

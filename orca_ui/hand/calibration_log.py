"""Persistent calibration-event history.

Every calibration run appends one JSON line next to the hand's
calibration.yaml (``calibration_history.jsonl``): timestamps, the requested
scope, and the raw progress events — including the magnet counts sampled at
both hardstops — so successive runs can be compared for encoder-magnet
drift without keeping terminal scrollback around.
"""

from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

HISTORY_BASENAME = "calibration_history.jsonl"
MAX_RUNS_RETURNED = 50

_lock = threading.Lock()


def history_path(calibration_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(calibration_path)),
                        HISTORY_BASENAME)


def append_run(calibration_path: str, record: dict) -> str | None:
    """Best-effort append; a failed write never fails the calibration."""
    try:
        path = history_path(calibration_path)
        line = json.dumps(record, separators=(",", ":"), default=str)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return path
    except Exception:
        logger.exception("could not append calibration history")
        return None


def read_runs(calibration_path: str,
              limit: int = MAX_RUNS_RETURNED) -> list[dict]:
    """Most recent run first; unparseable lines are skipped."""
    try:
        with _lock, open(history_path(calibration_path),
                         encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    runs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(runs))[:max(1, limit)]

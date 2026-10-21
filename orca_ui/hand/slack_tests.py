"""Slack tests for one hand (``slack_tests.yaml``), and the calibration gate
they drive.

Each run of the slack test (how far every finger motor turns at a current too
low to move a tensioned joint) is kept beside the hand's calibration with the
hand it was made on. The newest test on a hand decides whether it may be
calibrated: a motor that completed the half turn would unspool its tendon under
the calibration drive, so the hand has to be tensioned and tested again first.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from orca_core.utils.utils import read_yaml, write_yaml_atomic

TESTS_FILE = "slack_tests.yaml"
KEEP = 50


def tests_path(config) -> str:
    return os.path.join(os.path.dirname(config.calibration_path), TESTS_FILE)


def _load(config) -> dict:
    data = read_yaml(tests_path(config)) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("tests", {})
    return data


def save(config, report: dict, *, hand_key: str | None = None, motor_type: str | None = None) -> str:
    """Store one slack test keyed by its time; the oldest are dropped past ``KEEP``."""
    data = _load(config)
    key = datetime.now(timezone.utc).isoformat(timespec="seconds")
    while key in data["tests"]:
        key += "+"
    data["tests"][key] = {
        "recorded_at": key.rstrip("+"),
        "hand_key": hand_key,
        "motor_type": motor_type,
        **report,
    }
    for old in sorted(data["tests"])[:-KEEP]:
        del data["tests"][old]
    write_yaml_atomic(tests_path(config), data)
    return key


def latest_for_hand(config, hand_key: str | None) -> tuple[str, dict] | None:
    """(key, test) of the newest slack test on ``hand_key``; with no hand key,
    the newest test in the file (mock, or a board without an identity)."""
    tests = _load(config)["tests"]
    mine = [(k, t) for k, t in tests.items() if hand_key is None or t.get("hand_key") == hand_key]
    if not mine:
        return None
    # Two tests within the same second differ only by the key's suffix.
    return max(mine, key=lambda kv: (kv[1].get("recorded_at", ""), kv[0]))


def summary(config, hand_key: str | None) -> dict | None:
    """What the Setup tab shows for the hand's newest slack test."""
    found = latest_for_hand(config, hand_key)
    if found is None:
        return None
    key, test = found
    results = test.get("results") or []
    return {
        "key": key,
        "recorded_at": test.get("recorded_at"),
        "blocked": bool(test.get("blocked")),
        "current_ma": (test.get("settings") or {}).get("current_ma"),
        "results": {
            r["joint"]: {
                "motor": r.get("motor_id"),
                "total_deg": r.get("total_deg"),
                "plus_deg": r.get("plus_deg"),
                "minus_deg": r.get("minus_deg"),
                "status": r.get("status"),
            }
            for r in results
        },
    }


def calibration_block(config, hand_key: str | None) -> str | None:
    """Why the hand may not be calibrated, or None: the newest slack test found
    motors that turned the whole half turn."""
    found = latest_for_hand(config, hand_key)
    if found is None or not found[1].get("blocked"):
        return None
    joints = [r["joint"] for r in found[1].get("results") or [] if r.get("status") == "unspool"]
    return (
        f"the slack test turned {', '.join(joints) or 'a motor'} half a turn without a tendon "
        "going taut: calibrating would unspool it. Tension the hand and run the slack test again."
    )


def state(config) -> dict:
    data = _load(config)
    return {
        "tests": {
            k: {**t, "results": t.get("results") or []}
            for k, t in sorted(data["tests"].items(), key=lambda kv: kv[1].get("recorded_at", ""), reverse=True)
        }
    }

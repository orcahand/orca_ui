"""Slack tests (the ``slack_tests`` section of setup.yaml), and the
calibration gate they drive.

Each run of the slack test (how far each finger motor turns while the operator
holds its joint) is kept in the hand's own folder: setup.yaml holds the newest,
the archive the older ones. The newest test decides whether the hand may be
calibrated: a joint with more than half a turn of slack would unspool its
tendon under the calibration drive, so the hand has to be tensioned and tested
again first.
"""

from __future__ import annotations

from datetime import datetime, timezone

from orca_ui.hand import reference
from orca_ui.hand.hand_store import archived_records, read_records, update_records

SECTION = "slack_tests"


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    data.setdefault("tests", {})
    return data


def _load(config) -> dict:
    return _normalize(read_records(config, SECTION))


def save(config, report: dict, *, hand_key: str | None = None, motor_type: str | None = None) -> str:
    """Store one slack test keyed by its time; the one it replaces goes to the archive."""
    saved = []

    def add(data) -> dict:
        data = _normalize(data)
        key = datetime.now(timezone.utc).isoformat(timespec="seconds")
        while key in data["tests"]:
            key += "+"
        data["tests"][key] = {
            "recorded_at": key.rstrip("+"),
            "hand_key": hand_key,
            "motor_type": motor_type,
            **report,
        }
        saved.append(key)
        return data

    update_records(config, SECTION, add)
    return saved[-1]


def latest(config) -> tuple[str, dict] | None:
    """(key, test) of the newest slack test on the hand ``config`` is filed under."""
    tests = _load(config)["tests"]
    if not tests:
        return None
    # Two tests within the same second differ only by the key's suffix.
    return max(tests.items(), key=lambda kv: (kv[1].get("recorded_at", ""), kv[0]))


def summary(config) -> dict | None:
    """What the Setup tab shows for the hand's newest slack test."""
    found = latest(config)
    if found is None:
        return None
    key, test = found
    results = test.get("results") or []
    return {
        "key": key,
        "recorded_at": test.get("recorded_at"),
        "blocked": bool(test.get("blocked")),
        "current_ma": (test.get("settings") or {}).get("current_ma"),
        "deg_per_click": reference.deg_per_click(),
        "results": {
            r["joint"]: {
                "motor": r.get("motor_id"),
                "total_deg": r.get("total_deg"),
                "clicks": None if r.get("status") == "skipped" else reference.clicks_for_slack(r.get("total_deg"), r["joint"]),
                "ref_deg": reference.slack(config, None).get(r["joint"]),
                "plus_deg": r.get("plus_deg"),
                "minus_deg": r.get("minus_deg"),
                "status": r.get("status"),
            }
            for r in results
        },
    }


def calibration_block(config) -> str | None:
    """Why the hand may not be calibrated, or None: the newest slack test found
    joints with more than half a turn of slack."""
    found = latest(config)
    if found is None or not found[1].get("blocked"):
        return None
    joints = [r["joint"] for r in found[1].get("results") or [] if r.get("status") == "fail"]
    return (
        f"the slack test found more than half a turn of slack on {', '.join(joints) or 'a joint'}: "
        "calibrating would unspool it. Tension the hand and run the slack test again."
    )


def state(config) -> dict:
    """Every slack test on the hand, newest first, archived ones included."""
    tests = {**archived_records(config, SECTION), **_load(config)["tests"]}
    return {
        "tests": {
            k: {**t, "results": t.get("results") or []}
            for k, t in sorted(tests.items(), key=lambda kv: kv[1].get("recorded_at", ""), reverse=True)
        }
    }

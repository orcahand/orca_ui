"""Slack tests (the ``slack_tests`` section of setup.yaml), and the
calibration gate they drive.

Each run of the slack test (how far each finger motor turns while the operator
holds its joint) is kept beside the hand's calibration with the hand it was
made on. The newest test on a hand decides whether it may be calibrated: a
joint with more than half a turn of slack would unspool its tendon under the
calibration drive, so the hand has to be tensioned and tested again first.
"""

from __future__ import annotations

from datetime import datetime, timezone

from orca_core.maintenance.setup_file import read_section, write_section

from orca_ui.hand import reference

SECTION = "slack_tests"
KEEP = 50


def _load(config) -> dict:
    data = read_section(config, SECTION, legacy="slack_tests.yaml") or {}
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
    write_section(config, SECTION, data)
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


def calibration_block(config, hand_key: str | None) -> str | None:
    """Why the hand may not be calibrated, or None: the newest slack test found
    joints with more than half a turn of slack."""
    found = latest_for_hand(config, hand_key)
    if found is None or not found[1].get("blocked"):
        return None
    joints = [r["joint"] for r in found[1].get("results") or [] if r.get("status") == "fail"]
    return (
        f"the slack test found more than half a turn of slack on {', '.join(joints) or 'a joint'}: "
        "calibrating would unspool it. Tension the hand and run the slack test again."
    )


def state(config) -> dict:
    data = _load(config)
    return {
        "tests": {
            k: {**t, "results": t.get("results") or []}
            for k, t in sorted(data["tests"].items(), key=lambda kv: kv[1].get("recorded_at", ""), reverse=True)
        }
    }

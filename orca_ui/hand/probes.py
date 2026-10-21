"""Named tension-probe datasets for one hand (``tension_probes.yaml``).

Each probe run (slack take-up and breakaway current per tendon and direction)
is saved under a name such as ``GT_tension_00`` beside the hand's calibration,
with the travel baseline that was active and the settings used, so runs on the
same hand — or across hands — can be compared.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone

from orca_core.utils.utils import read_yaml, write_yaml_atomic

PROBES_FILE = "tension_probes.yaml"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
DEFAULT_PREFIX = "GT_tension_"
# A take-up that got within this of its travel cap did not stall on a taut tendon:
# the motor slowed for its goal. The joint followed freely, or the slack is beyond
# the cap; either way it is not a slack measurement.
FREE_RUN_MARGIN_DEG = 3.5


def ran_free(result: dict) -> bool:
    free, cap = result.get("free_deg"), result.get("cap_deg")
    return not result.get("stalled") or (
        free is not None and cap is not None and float(free) >= float(cap) - FREE_RUN_MARGIN_DEG
    )


def probes_path(config) -> str:
    return os.path.join(os.path.dirname(config.calibration_path), PROBES_FILE)


def _load(config) -> dict:
    data = read_yaml(probes_path(config)) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("probes", {})
    data.setdefault("clicks", {})
    data.setdefault("reference", None)
    return data


def dataset_name(config, kind: str) -> str:
    """A name that says what and when: ``check_20261021_094012``; a second
    dataset in the same second gets a letter suffix."""
    base = f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    taken = _load(config)["probes"]
    name = base
    for suffix in "bcdefgh":
        if name not in taken:
            return name
        name = f"{base}{suffix}"
    return name


def next_name(config, prefix: str = DEFAULT_PREFIX) -> str:
    """``GT_tension_00``, ``GT_tension_01``, ... after the highest one saved."""
    taken = [
        int(m.group(1))
        for n in _load(config)["probes"]
        if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", n))
    ]
    return f"{prefix}{(max(taken) + 1 if taken else 0):02d}"


def save(
    config,
    name: str | None,
    report: dict,
    *,
    hand_key: str | None = None,
    baseline: str | None = None,
    note: str | None = None,
    motor_type: str | None = None,
) -> str:
    """Store a probe report under ``name`` (or the next free default name)."""
    data = _load(config)
    name = name or next_name(config)
    if not NAME_RE.match(name):
        raise ValueError("probe names are 1-40 characters: letters, digits, _ . -")
    if name in data["probes"]:
        raise KeyError(
            f"probe {name!r} already exists; probe datasets are never overwritten"
        )
    data["probes"][name] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hand_key": hand_key,
        "baseline": baseline,
        "motor_type": motor_type,
        "note": note,
        **report,
    }
    write_yaml_atomic(probes_path(config), data)
    return name


def set_reference(config, name: str | None) -> None:
    """Mark a saved dataset as the reference later probes are scored against;
    None clears it."""
    data = _load(config)
    if name is not None and name not in data["probes"]:
        raise KeyError(f"no probe dataset named {name!r}")
    data["reference"] = name
    write_yaml_atomic(probes_path(config), data)


def reference(config) -> tuple[str, dict] | None:
    """(name, dataset) of the reference probe, or None."""
    data = _load(config)
    name = data.get("reference")
    if name and name in data["probes"]:
        return name, data["probes"][name]
    return None


def latest_for_hand(config, hand_key: str | None) -> tuple[str, dict] | None:
    """(name, dataset) of the newest probe recorded on ``hand_key``, or None."""
    if not hand_key:
        return None
    probes = _load(config)["probes"]
    mine = [(n, p) for n, p in probes.items() if p.get("hand_key") == hand_key]
    if not mine:
        return None
    return max(mine, key=lambda kv: kv[1].get("recorded_at", ""))


def probe_slack(
    config, hand_key: str | None, since: str | None = None
) -> tuple[str, dict[str, float]] | None:
    """Slack per joint (motor degrees) from this hand's newest probe: the
    largest stalled take-up free travel over both senses, leaving out runs that
    reached the travel cap (see :func:`ran_free`). None when there is no probe
    for the hand, or when it predates ``since`` (an ISO timestamp, normally the
    last completed tensioning) and so describes an older state."""
    found = latest_for_hand(config, hand_key)
    if found is None:
        return None
    name, dataset = found
    if since and (dataset.get("recorded_at") or "") <= since:
        return None
    slack: dict[str, float] = {}
    for r in dataset.get("results") or []:
        if r.get("method") != "takeup" or r.get("skipped") or ran_free(r):
            continue
        slack[r["joint"]] = max(slack.get(r["joint"], 0.0), float(r["free_deg"]))
    return name, slack


def click_model(config) -> dict:
    """What one ratchet click takes up, in motor degrees of take-up slack, from
    the saved click tests: per joint where measured, and the mean over all of
    them as the fallback. Empty until a click test has been run."""
    per_joint: dict[str, list[float]] = {}
    for record in _load(config)["clicks"].values():
        joint = record.get("joint")
        for rnd in record.get("rounds") or []:
            values = [v for v in (rnd.get("per_click_deg") or {}).values() if v is not None]
            if joint and values:
                # Clicks take up one tendon: the sense that moved is the measurement.
                per_joint.setdefault(joint, []).append(max(values))
    joints = {j: round(sum(v) / len(v), 3) for j, v in per_joint.items() if v}
    positive = [v for v in joints.values() if v > 0]
    return {
        "per_joint": joints,
        "default": round(sum(positive) / len(positive), 3) if positive else None,
        "samples": sum(len(v) for v in per_joint.values()),
    }


def clicks_left(model: dict, joint: str, slack_deg: float | None) -> int | None:
    """Ratchet clicks that take up ``slack_deg`` on ``joint`` by the click model."""
    if slack_deg is None or slack_deg <= 0:
        return 0 if slack_deg is not None else None
    per_click = (model.get("per_joint") or {}).get(joint)
    if not per_click or per_click <= 0:
        per_click = model.get("default")
    if not per_click or per_click <= 0:
        return None
    return int(math.ceil(slack_deg / per_click))


def save_clicks(config, record: dict) -> str:
    """Store one ratchet-click measurement (degrees per click) keyed by time."""
    data = _load(config)
    key = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["clicks"][key] = record
    write_yaml_atomic(probes_path(config), data)
    return key


def state(config) -> dict:
    data = _load(config)
    return {
        "probes": {
            n: dict(p)
            for n, p in sorted(
                data["probes"].items(),
                key=lambda kv: kv[1].get("recorded_at", ""),
                reverse=True,
            )
        },
        "clicks": dict(data["clicks"]),
        "reference": data["reference"] if data["reference"] in data["probes"] else None,
        "next_name": next_name(config),
    }

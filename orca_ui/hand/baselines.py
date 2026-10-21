"""Named motor-travel baselines for one hand (``travel_baselines.yaml``).

orca_core keeps a single ``calibration.yaml`` per hand, so each calibration
overwrites the last. This module snapshots every run beside it and lets the
operator promote one snapshot to a named ground truth (``GT_01`` ...) that
guided tensioning scores against instead of the shared v2.1 baseline.

File layout, beside the hand's calibration.yaml::

    active: GT_01
    snapshots:
      manual_2026-10-15T18-44-02:
        recorded_at: "2026-10-15T16:44:02+00:00"
        source: manual            # manual | auto | import
        hand_key: ser-9097
        travel: {index_pip: 101.69, ...}     # motor degrees between hardstops
        ratios: {index_pip: 0.0145, ...}     # motor rad per joint degree
        limits: {index_pip: [-1.23, 0.54], ...}
    baselines:
      GT_01: {from_snapshot: manual_..., recorded_at, source, travel, note}
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone

from orca_core.utils.utils import read_yaml, write_yaml_atomic

BASELINES_FILE = "travel_baselines.yaml"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
SOURCES = ("manual", "auto", "import")


def baselines_path(config) -> str:
    return os.path.join(os.path.dirname(config.calibration_path), BASELINES_FILE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(config) -> dict:
    data = read_yaml(baselines_path(config)) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("active", None)
    data.setdefault("snapshots", {})
    data.setdefault("baselines", {})
    return data


def _save(config, data: dict) -> None:
    write_yaml_atomic(baselines_path(config), data)


def travel_from_calibration(config, calibration) -> dict[str, float]:
    """Motor travel per joint in degrees: the recorded ``motor_travel_measured``
    when the run wrote one, else derived from the motor limits."""
    measured = dict(getattr(calibration, "motor_travel_measured_dict", {}) or {})
    if measured:
        return {j: round(float(t), 2) for j, t in measured.items()}
    out = {}
    for joint, motor in config.joint_to_motor_map.items():
        limits = calibration.motor_limits_dict.get(abs(int(motor)))
        if limits and None not in limits:
            out[joint] = round(
                math.degrees(abs(float(limits[1]) - float(limits[0]))), 2
            )
    return out


def snapshot_calibration(
    config,
    calibration,
    *,
    source: str,
    hand_key: str | None = None,
    note: str | None = None,
    recorded_at: str | None = None,
    joints: list[str] | None = None,
    partial: bool = False,
) -> str:
    """Record a calibration result as a snapshot; returns its name. ``partial``
    marks a run that did not calibrate every finger joint (values for the
    others are the previous run's), which the console will not promote."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    recorded_at = recorded_at or _now()
    stamp = recorded_at.replace(":", "-")[:19]
    name = f"{source}_{stamp}"
    joint_of = {abs(int(m)): j for j, m in config.joint_to_motor_map.items()}
    ratios = {
        joint_of[m]: round(float(r), 5)
        for m, r in (calibration.joint_to_motor_ratios_dict or {}).items()
        if m in joint_of and r
    }
    limits = {
        joint_of[m]: [round(float(v), 4) for v in lim]
        for m, lim in (calibration.motor_limits_dict or {}).items()
        if m in joint_of and lim and None not in lim
    }
    entry = {
        "recorded_at": recorded_at,
        "source": source,
        "hand_key": hand_key,
        "partial": bool(partial),
        "joints": list(joints) if joints is not None else None,
        "travel": travel_from_calibration(config, calibration),
        "ratios": ratios,
        "limits": limits,
    }
    if note:
        entry["note"] = note
    data = _load(config)
    data["snapshots"][name] = entry
    _save(config, data)
    return name


def snapshot_from_file(
    config,
    calibration_path: str,
    *,
    source: str,
    recorded_at: str | None = None,
    hand_key: str | None = None,
    note: str | None = None,
    partial: bool = False,
) -> str:
    """Snapshot a saved calibration.yaml (e.g. one rescued before an overwrite)."""
    from orca_core.calibration import CalibrationResult

    calibration = CalibrationResult.from_calibration_path(
        calibration_path, config.motor_ids
    )
    return snapshot_calibration(
        config,
        calibration,
        source=source,
        hand_key=hand_key,
        note=note,
        recorded_at=recorded_at,
        partial=partial,
    )


def import_travel(
    config,
    name: str,
    travel: dict[str, float],
    *,
    source: str = "import",
    recorded_at: str | None = None,
    note: str | None = None,
) -> None:
    """Add a baseline straight from a travel table (no snapshot behind it)."""
    _check_name(name)
    data = _load(config)
    data["baselines"][name] = {
        "from_snapshot": None,
        "recorded_at": recorded_at or _now(),
        "source": source,
        "note": note,
        "travel": {j: round(float(t), 2) for j, t in travel.items()},
    }
    _save(config, data)


def promote(
    config, snapshot: str, name: str, note: str | None = None, activate_it: bool = True
) -> dict:
    """Name a snapshot as a baseline (and make it the active one by default)."""
    _check_name(name)
    data = _load(config)
    entry = data["snapshots"].get(snapshot)
    if entry is None:
        raise KeyError(f"no snapshot named {snapshot!r}")
    if entry.get("partial"):
        raise ValueError(f"{snapshot} is a partial run; a baseline needs a full calibration")
    if name in data["baselines"]:
        raise KeyError(
            f"baseline {name!r} already exists; baselines are never overwritten"
        )
    data["baselines"][name] = {
        "from_snapshot": snapshot,
        "recorded_at": entry["recorded_at"],
        "source": entry["source"],
        "note": note,
        "travel": dict(entry["travel"]),
    }
    if activate_it:
        data["active"] = name
    _save(config, data)
    return data["baselines"][name]


def activate(config, name: str | None) -> None:
    """Make ``name`` the baseline guided tensioning scores against; None falls
    back to the shared v2.1 block."""
    data = _load(config)
    if name is not None and name not in data["baselines"]:
        raise KeyError(f"no baseline named {name!r}")
    data["active"] = name
    _save(config, data)


def active_baseline(config) -> tuple[str, dict] | None:
    """(name, entry) of the active baseline, or None."""
    data = _load(config)
    name = data.get("active")
    entry = data["baselines"].get(name) if name else None
    return (name, entry) if entry else None


def active_travel(config) -> dict[str, float] | None:
    found = active_baseline(config)
    return dict(found[1]["travel"]) if found else None


def state(config) -> dict:
    """What the console shows: the active name plus every baseline and snapshot."""
    data = _load(config)
    shared = {
        j: config.expected_motor_travel_deg(j, any_hardware=True)
        for j in config.joint_ids
        if j in config.joint_to_motor_map
    }
    return {
        "active": data.get("active"),
        "shared": {j: t for j, t in shared.items() if t is not None},
        "baselines": {n: dict(e) for n, e in data["baselines"].items()},
        "snapshots": {
            n: dict(e)
            for n, e in sorted(
                data["snapshots"].items(),
                key=lambda kv: kv[1].get("recorded_at", ""),
                reverse=True,
            )
        },
    }


def slack_estimate(config, hand_key: str | None, last_tension: dict | None) -> dict | None:
    """Per-joint slack from two sweeps of the same hand in the same state: the
    motor-driven calibration reaches the hardstops plus the slack, the hand sweep
    of the final tensioning round reaches them minus the slack. Half the
    difference is the slack, half the sum the hand's own travel. Needs a full
    calibration snapshot of ``hand_key`` taken after the tensioning completed."""
    if not hand_key or not last_tension or not last_tension.get("spread_deg"):
        return None
    done_at = last_tension.get("completed_at") or ""
    snapshots = [
        (n, e)
        for n, e in _load(config)["snapshots"].items()
        if e.get("hand_key") == hand_key
        and not e.get("partial")
        and (e.get("recorded_at") or "") > done_at
    ]
    if not snapshots:
        return None
    name, entry = max(snapshots, key=lambda kv: kv[1].get("recorded_at", ""))
    joints = {}
    for joint, swept in last_tension["spread_deg"].items():
        motor = (entry.get("travel") or {}).get(joint)
        if swept is None or motor is None:
            continue
        joints[joint] = {
            "sweep_deg": round(float(swept), 2),
            "motor_deg": round(float(motor), 2),
            "slack_deg": round((float(motor) - float(swept)) / 2, 2),
            "travel_deg": round((float(motor) + float(swept)) / 2, 2),
        }
    return {
        "snapshot": name,
        "calibrated_at": entry.get("recorded_at"),
        "tensioned_at": done_at,
        "joints": joints,
    }


def _check_name(name: str) -> None:
    if not NAME_RE.match(name or ""):
        raise ValueError("baseline names are 1-40 characters: letters, digits, _ . -")

"""Named motor-travel baselines (the ``travel_baselines`` section of setup.yaml).

orca_core keeps a single ``calibration.yaml`` per hand (and the one before
it), so each calibration overwrites the last. This module snapshots every run
in the hand's folder and lets the operator promote one snapshot to a named
ground truth (``GT_01`` ...) that guided tensioning scores against instead of
the shared v2.1 baseline. setup.yaml keeps the newest snapshot, the newest
complete one, the newest baseline and the active one; the rest go to the
hand's archive, where they can be read but no longer promoted.

Section layout::

    active: GT_01
    snapshots:
      manual_2026-10-15T18-44-02:
        recorded_at: "2026-10-15T16:44:02+00:00"
        source: manual            # manual | auto | import
        travel: {index_pip: 101.69, ...}     # motor degrees between hardstops
        ratios: {index_pip: 0.0145, ...}     # motor rad per joint degree
        limits: {index_pip: [-1.23, 0.54], ...}
    baselines:
      GT_01: {from_snapshot: manual_..., recorded_at, source, travel, note}
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from orca_ui.hand.hand_store import archived_records, read_records, update_records

SECTION = "travel_baselines"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
SOURCES = ("manual", "auto", "import")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    data.setdefault("active", None)
    data.setdefault("snapshots", {})
    data.setdefault("baselines", {})
    return data


def _load(config) -> dict:
    return _normalize(read_records(config, SECTION))


def _update(config, change) -> dict:
    """Apply ``change`` to the section in place, re-read and stored under setup.yaml's lock."""

    def apply(data):
        data = _normalize(data)
        change(data)
        return data

    return update_records(config, SECTION, apply)


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
        "partial": bool(partial),
        "joints": list(joints) if joints is not None else None,
        "travel": travel_from_calibration(config, calibration),
        "ratios": ratios,
        "limits": limits,
    }
    if note:
        entry["note"] = note
    _update(config, lambda data: data["snapshots"].__setitem__(name, entry))
    return name


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
    baseline = {
        "from_snapshot": None,
        "recorded_at": recorded_at or _now(),
        "source": source,
        "note": note,
        "travel": {j: round(float(t), 2) for j, t in travel.items()},
    }
    _update(config, lambda data: data["baselines"].__setitem__(name, baseline))


def promote(
    config, snapshot: str, name: str, note: str | None = None, activate_it: bool = True
) -> dict:
    """Name a snapshot as a baseline (and make it the active one by default);
    returns the baseline stored, which the archive may already hold."""
    _check_name(name)
    archived = archived_records(config, f"{SECTION}-baselines")
    stored = {}

    def change(data: dict) -> None:
        entry = data["snapshots"].get(snapshot)
        if entry is None:
            raise KeyError(f"no snapshot named {snapshot!r} is kept for promotion: "
                           "only the newest calibrations can become a baseline")
        if entry.get("partial"):
            raise ValueError(f"{snapshot} is a partial run; a baseline needs a full calibration")
        if name in data["baselines"] or name in archived:
            raise KeyError(
                f"baseline {name!r} already exists; baselines are never overwritten"
            )
        stored.update(
            from_snapshot=snapshot,
            recorded_at=entry["recorded_at"],
            source=entry["source"],
            note=note,
            travel=dict(entry["travel"]),
        )
        data["baselines"][name] = dict(stored)
        if activate_it:
            data["active"] = name

    _update(config, change)
    return stored


def activate(config, name: str | None) -> None:
    """Make ``name`` the baseline guided tensioning scores against, bringing it
    back from the archive if it was moved there; None falls back to the shared
    v2.1 block."""
    archived = archived_records(config, f"{SECTION}-baselines") if name is not None else {}

    def change(data: dict) -> None:
        if name is not None and name not in data["baselines"]:
            if not isinstance(archived.get(name), dict):
                raise KeyError(f"no baseline named {name!r}")
            data["baselines"][name] = dict(archived[name])
        data["active"] = name

    _update(config, change)


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
    """What the console shows: the active name plus every baseline and snapshot,
    archived ones marked ``archived`` (readable, not promotable)."""
    data = _load(config)
    for kind in ("snapshots", "baselines"):
        for name, entry in archived_records(config, f"{SECTION}-{kind}").items():
            if name not in data[kind] and isinstance(entry, dict):
                data[kind][name] = {**entry, "archived": True}
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


def _check_name(name: str) -> None:
    if not NAME_RE.match(name or ""):
        raise ValueError("baseline names are 1-40 characters: letters, digits, _ . -")

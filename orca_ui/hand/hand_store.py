"""Everything the console asks of orca_core's hand store, in one place.

orca_core keeps each physical hand's files under ``<ORCA_HOME>/hands/<id>/``
(identity, nickname, calibration and the previous one, measured joint ranges,
setup records). The console only ever reaches them through these functions, so
a change in core's API is a change here and nowhere else.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable

from orca_core import hand_store as core_store
from orca_core.maintenance import setup_file


class NoHandFolder(RuntimeError):
    """No hand has connected yet, so there is no folder for its records."""


# --- setup records (setup.yaml in the hand's folder, and its archive) ---------


def has_folder(config) -> bool:
    return bool(getattr(config, "hand_dir", ""))


def read_records(config, section: str) -> Any:
    """``section`` of the hand's setup.yaml; None when absent or no hand is known."""
    return setup_file.read_section(config, section) if has_folder(config) else None


def update_records(config, section: str, fn: Callable[[Any], Any]) -> Any:
    """Change ``section`` under setup.yaml's lock; returns what was stored."""
    if not has_folder(config):
        raise NoHandFolder("connect the hand first: its records are kept in its own folder")
    return setup_file.update_section(config, section, fn)


def archived_records(config, section: str) -> dict:
    """``{name: record}`` the hand's setup.yaml no longer keeps, from its archive."""
    if not has_folder(config):
        return {}
    return setup_file.read_archive(config, section) or {}


def hardware_version_in_force(*, override: int | None, board: int | None,
                              model: int | None) -> int | None:
    """The session's choice, else the board's report, else a version
    config.yaml pins: the order orca_core settles it in at connect."""
    for version in (override, board, model):
        if version is not None:
            return version
    return None


# What a hand settles at connect: the version in force, the map and ranges it
# selects (with the ranges measured on this hand), and the hand's folder.
SETTLED_FIELDS = (
    "hardware_version", "joint_to_motor_map", "joint_inversion_dict", "joint_roms_dict",
    "measured_joint_roms_dict", "base_joint_to_motor_map", "base_joint_roms_dict",
    "hand_dir", "calibration_path",
)


def settled_config(config, settled):
    """``config`` with what a connected hand settled (``settled``, its config)."""
    return dataclasses.replace(config, **{
        name: getattr(settled, name) for name in SETTLED_FIELDS
        if hasattr(config, name) and hasattr(settled, name)})


def prepare_hand(hand, hardware_version: int | None) -> None:
    """Carry the session's hardware version choice into a hand about to connect."""
    if hardware_version is not None:
        hand.set_hardware_version(hardware_version)


class StoreRefused(RuntimeError):
    """orca_core refused the change for this hand (nothing to restore, a bad name)."""


def details(hand, hand_id: str) -> dict:
    """The hand block of ``/api/hand/info``: who the hand is and what is on file.
    ``hand`` is the connected hand, or None."""
    return {
        "id": hand_id,
        "folder": (hand.hand_dir or None) if hand is not None else None,
        "nickname": hand.nickname if hand is not None else None,
        "calibration": calibration_record(hand),
        "joint_ranges": joint_ranges(hand),
    }


def set_nickname(hand, value: str | None) -> str | None:
    """Name the hand for display (None clears it); returns the name stored."""
    try:
        return hand.set_nickname(value)
    except (RuntimeError, core_store.HandStoreError) as e:
        raise StoreRefused(str(e)) from e


def calibration_record(hand) -> dict:
    """When the calibration in force was taken, which file holds it, and
    whether a previous one can be restored."""
    info = hand.calibration_info if hand is not None else {}
    previous = info.get("previous") or None
    return {
        "calibrated_at": info.get("calibrated_at"),
        "sequence": info.get("sequence"),
        "path": info.get("path"),
        "previous_available": previous is not None,
        "previous_at": previous.get("calibrated_at") if previous else None,
    }


def joint_ranges(hand) -> dict:
    """``source`` is ``model`` (the model's defaults) or ``measured`` (on this
    hand, at ``measured_at``); ``path`` is where measured ranges are read from."""
    info = hand.joint_ranges_info if hand is not None else {}
    folder = getattr(hand, "hand_dir", None) if hand is not None else None
    return {"source": info.get("source", "model"), "measured_at": info.get("measured_at"),
            "path": os.path.join(folder, core_store.JOINT_RANGES_FILE) if folder else None}


def restore_previous_calibration(hand) -> str:
    """Put the previous calibration back in force (again undoes it); returns the file."""
    try:
        return hand.restore_previous_calibration()["path"]
    except FileNotFoundError as e:
        raise StoreRefused(str(e)) from e


def board_calibration_newer(hand) -> dict | None:
    """``{"board": {...}, "computer": {...}}`` (each ``sequence`` and
    ``calibrated_at``) when the board held a newer calibration than this
    computer at connect, else None."""
    return hand.board_calibration_newer()


def keep_computer_calibration(hand) -> None:
    """Stop offering the board's calibration until either side's changes."""
    hand.keep_computer_calibration()


def adopt_board_calibration(hand) -> str:
    """Take the board's calibration as this computer's (the replaced one becomes
    the previous); returns the file written."""
    try:
        return hand.adopt_board_calibration()["path"]
    except RuntimeError as e:
        raise StoreRefused(str(e)) from e


def legacy_files(hand) -> list[str]:
    """Per-hand files from before the hand store, found beside the model's
    config when this hand's folder was created; they are not used."""
    return list(hand.legacy_files) if hand is not None else []


def dismiss_legacy_files(hand) -> None:
    hand.dismiss_legacy_files()

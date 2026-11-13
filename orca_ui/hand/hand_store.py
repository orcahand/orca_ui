"""Everything the console asks of orca_core's hand store, in one place.

orca_core keeps each physical hand's files under ``<ORCA_HOME>/hands/<id>/``
(identity, nickname, calibration and the previous one, measured joint ranges,
setup records). The console only ever reaches them through these functions, so
a change in core's API is a change here and nowhere else.
"""

from __future__ import annotations


class StoreUnavailable(RuntimeError):
    """The installed orca_core cannot do this for the hand."""


def store_hand_id(board_hand_id: str | None, model_name: str) -> str:
    """The id a hand is filed under: its board's (serial, else board ID), or
    one shared id per model for hands that report none."""
    return board_hand_id or f"noboard-{model_name}"


def hardware_version_in_force(*, override: int | None, board: int | None,
                              model: int | None) -> int | None:
    """The console's session choice, else the board's report, else the model's."""
    for version in (override, board, model):
        if version is not None:
            return version
    return None


def details(hand, hand_id: str) -> dict:
    """The hand block of ``/api/hand/info``: who the hand is and what is on file."""
    return {
        "id": hand_id,
        "nickname": nickname(hand),
        "calibration": calibration_record(hand),
        "joint_ranges": joint_ranges(hand),
    }


def nickname(hand) -> str | None:
    return None


def set_nickname(hand, value: str | None) -> None:
    raise StoreUnavailable("this orca_core keeps no nickname for a hand")


def calibration_record(hand) -> dict:
    """When the calibration in force was taken, which file holds it, and
    whether a previous one can be restored."""
    path = getattr(getattr(hand, "config", None), "calibration_path", None) if hand else None
    return {"calibrated_at": None, "sequence": None, "path": path,
            "previous_at": None, "previous_available": False}


def joint_ranges(hand) -> dict:
    """``source`` is ``model`` (the model's defaults) or ``measured`` (on this
    hand, at ``measured_at``)."""
    return {"source": "model", "measured_at": None}


def restore_previous_calibration(hand) -> str:
    """Put the previous calibration back in force; returns the file written."""
    raise StoreUnavailable("this orca_core keeps no previous calibration")


def board_calibration_newer(hand) -> dict | None:
    """``{"board": {...}, "computer": {...}}`` (each ``sequence`` and
    ``calibrated_at``) when the board holds a newer calibration than this
    computer, else None."""
    return None


def keep_computer_calibration(hand) -> None:
    """Stop offering the board's calibration until either side's changes."""
    raise StoreUnavailable("this orca_core cannot remember a choice about the board's calibration")


def adopt_board_calibration(hand) -> str:
    """Take the board's calibration as this computer's; returns the file written."""
    raise StoreUnavailable("this orca_core cannot read a board's calibration")


def legacy_files(hand) -> list[str]:
    """Per-hand files from before the hand store, found beside the model's
    config when this hand's folder was created; they are not used."""
    return []

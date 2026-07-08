"""The adapter seam: every orca_core call made by operations lives here.

The user plans to refactor orca_core's motor side to a state-based system;
when that lands, this module is the single planned rewrite point — operations
themselves must not import orca_core directly.
"""

from __future__ import annotations

from typing import Callable

# Mirrors orca_core/scripts/calibrate.py (scripts aren't importable from the
# installed package). Expansion of finger names to joint lists is a frontend
# convenience; this mapping is kept here for validation and reuse.
FINGER_TO_JOINTS: dict[str, list[str]] = {
    "thumb": ["thumb_cmc", "thumb_abd", "thumb_mcp", "thumb_dip"],
    "index": ["index_abd", "index_mcp", "index_pip"],
    "middle": ["middle_abd", "middle_mcp", "middle_pip"],
    "ring": ["ring_abd", "ring_mcp", "ring_pip"],
    "pinky": ["pinky_abd", "pinky_mcp", "pinky_pip"],
    "wrist": ["wrist"],
}


def request_stop(hand) -> None:
    """Interrupt a blocking calibrate()/tension() from another thread.

    orca_core has no public API for this outside stop_task() (which joins a
    background thread we don't use); setting the task stop event is the
    supported interrupt signal — the drive/hold loops poll it.
    """
    hand._task_stop_event.set()


def calibrate(
    hand,
    *,
    joints: list[str] | None,
    force_wrist: bool,
    joint_encoder_client,
    progress_callback: Callable[[dict], None],
) -> None:
    """Blocking calibration on the calling thread; interrupt via request_stop."""
    hand.calibrate(
        blocking=True,
        force_wrist=force_wrist,
        joints=joints,
        joint_encoder_client=joint_encoder_client,
        progress_callback=progress_callback,
    )


def tension(
    hand,
    *,
    move_motors: bool,
    progress_callback: Callable[[dict], None],
) -> None:
    """Blocking tension on the calling thread; interrupt via request_stop.

    The blocking path is deliberate: orca_core's background-task path has a
    lost-stop race (the task thread clears the stop event after start) and
    stop_task() joins without a timeout.
    """
    hand.tension(
        move_motors=move_motors,
        blocking=True,
        progress_callback=progress_callback,
    )


def pose_from_fractions(hand, fractions: dict[str, float]) -> dict[str, float]:
    """Resolve ROM-fraction pose definitions to joint angles in degrees."""
    pose = hand.pose_from_fractions(fractions)
    return {j: float(v) for j, v in pose.as_dict().items() if v is not None}

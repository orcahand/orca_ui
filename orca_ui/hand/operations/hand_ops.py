"""The adapter seam: every orca_core call made by operations lives here.

The user plans to refactor orca_core's motor side to a state-based system;
when that lands, this module is the single planned rewrite point — operations
themselves must not import orca_core directly.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

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


def build_maintenance_hand(config_path: str, stop_event: threading.Event,
                           retry_s: float = 2.0):
    """Fresh motor-only OrcaHand for a maintenance operation.

    Always the plain class — never the feedback subclass, whose 100 Hz loop
    refuses to calibrate. Port-open is retried briefly to absorb the OS
    serial release latency after the supervisor closed the session.
    """
    from orca_core.hardware_hand import OrcaHand

    hand = OrcaHand(config_path=config_path)
    deadline = time.monotonic() + retry_s
    last_message = ""
    while True:
        try:
            ok, last_message = hand.connect()
        except Exception as e:
            ok, last_message = False, str(e)
        if ok:
            return hand
        if stop_event.is_set():
            raise RuntimeError("stopped while connecting")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"maintenance connect failed: {last_message}")
        time.sleep(0.25)


def disconnect(hand) -> None:
    try:
        hand.disconnect()
    except Exception:
        logger.exception("maintenance hand disconnect failed")


def open_encoder_client(config, presence):
    """UI-owned encoder client for the calibration anchor pass (the
    scripts/calibrate.py pattern). Returns (client, owned_link), or
    (None, None) when feedback isn't configured or no encoder port exists.
    """
    if not getattr(config, "joint_feedback_enabled", False):
        return None, None
    port = getattr(getattr(presence, "sensing", None), "encoder", None)
    if not port:
        return None, None

    from orca_core.hardware.hand_serial_link import HandSerialLink
    from orca_core.hardware.joint_encoder_client import JointEncoderClient

    link = HandSerialLink(port=port, baudrate=config.encoder_baudrate)
    link.connect()
    try:
        client = JointEncoderClient(link)
        client.connect()
        client.start_stream()
    except Exception:
        try:
            link.disconnect()
        except Exception:
            pass
        raise
    return client, link


def close_encoder_client(client, link) -> None:
    if client is not None:
        try:
            client.disconnect()
        except Exception:
            pass
    if link is not None:
        try:
            link.disconnect()
        except Exception:
            pass


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

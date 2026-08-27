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
                           retry_s: float = 2.0,
                           config_overrides: "dict | None" = None):
    """Fresh motor-only OrcaHand for a maintenance operation.

    Always the plain class — never the feedback subclass, whose 100 Hz loop
    refuses to calibrate. Port-open is retried briefly to absorb the OS
    serial release latency after the supervisor closed the session.

    ``config_overrides`` swaps individual config fields for this hand only
    (e.g. a gentler ``calibration_current``) — config.yaml is untouched.
    """
    import dataclasses

    from orca_core import OrcaHand

    hand = OrcaHand(config_path=config_path)
    if config_overrides:
        # The config is a frozen dataclass: replace it wholesale before
        # connect, and re-validate so an inconsistent override (e.g. a
        # calibration current above max_current) fails here, not mid-sweep.
        hand.config = dataclasses.replace(hand.config, **config_overrides)
        hand.config.validate()
    deadline = time.monotonic() + retry_s
    last_message = ""
    while True:
        try:
            ok, last_message = hand.connect(interactive=False)
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
    return open_encoder_client_on_port(config, port)


def open_encoder_client_on_port(config, port: str):
    """Open a UI-owned encoder client on a known port. Returns (client, link)."""
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


def encoder_backed_joints(hand) -> list[str]:
    """Joints whose angle this hand reads from a joint encoder."""
    return list(hand._encoder_backed_joints())


def missing_encoder_anchors(hand) -> list[str]:
    """Encoder-backed joints without a recorded encoder anchor — nonempty
    means the joint sensors have never been (fully) calibrated."""
    anchored = hand.calibration.joint_encoder_calibration_dict
    return [j for j in hand._encoder_backed_joints() if j not in anchored]


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


def demo_definitions() -> dict[str, list[dict[str, float]]]:
    """orca_core's packaged demo poses as fraction-keyframe sequences.

    The presets carry poses only — playback timing is synthesized by the
    player (fixed per-segment duration). Deliberately not re-exported from
    the ``orca_core`` namespace, hence the explicit module import.
    """
    from orca_core.demo_poses import load_demo_poses

    return {
        name: [dict(demo.pose_fractions[pose]) for pose in demo.sequence]
        for name, demo in load_demo_poses().items()
    }


# ----- motor chain configuration (orca_core.maintenance.motor_chain) -----------
#
# Assembly-time motor ID'ing. orca_core ships this as an interaction-free
# library (progress/prompt callbacks + should_stop), so the wrappers here are
# deliberately thin — they exist only to keep every orca_core touchpoint
# inside the seam.


def known_motor_types() -> list[str]:
    from orca_core.constants import SUPPORTED_MOTOR_TYPES

    return list(SUPPORTED_MOTOR_TYPES)


def motor_models(motor_type: str) -> dict[str, str]:
    """{"finger": model, "wrist": model} for a motor family."""
    from orca_core.constants import MOTOR_MODELS

    return dict(MOTOR_MODELS[motor_type])


def chain_error_types() -> tuple[type, type]:
    """(MotorChainError, MotorChainAborted) for except clauses."""
    from orca_core.maintenance.motor_chain import (
        MotorChainAborted,
        MotorChainError,
    )

    return MotorChainError, MotorChainAborted


def resolve_motor_port(config, presence) -> str | None:
    """Motor bus port for chain work: the maintenance lease's probe result
    when it saw one, else the config's port / auto-detection."""
    if presence is not None and getattr(presence, "motor_port", None):
        return presence.motor_port
    from orca_core.maintenance.motor_chain import resolve_port

    port = getattr(config, "port", None)
    return resolve_port(None if port == "auto" else port,
                        getattr(config, "motor_type", None))


def detect_motor_type(port: str, progress_callback=None) -> str | None:
    from orca_core.maintenance.motor_chain import detect_motor_type as detect

    return detect(port, progress_callback=progress_callback)


def build_chain_plan(config, port: str, motor_type: str):
    """MotorChainPlan from an OrcaHandConfig (the library takes the raw
    config mapping)."""
    from orca_core.maintenance.motor_chain import plan_motor_chain

    return plan_motor_chain(
        {
            "motor_ids": list(config.motor_ids),
            "joint_to_motor_map": dict(config.joint_to_motor_map or {}),
            "baudrate": getattr(config, "baudrate", None),
        },
        port,
        motor_type,
    )


def run_chain_configure(plan, *, progress_callback, prompt_callback,
                        should_stop) -> list[int]:
    """Blocking guided assembly; returns the configured motor IDs."""
    from orca_core.maintenance.motor_chain import configure_motor_chain

    return configure_motor_chain(
        plan,
        progress_callback=progress_callback,
        prompt_callback=prompt_callback,
        should_stop=should_stop,
    )


def reset_motors_once(plan, *, progress_callback, prompt_callback,
                      should_stop) -> list[dict]:
    """One reset pass over whatever is on the bus (the caller loops)."""
    from orca_core.maintenance.motor_chain import reset_all_motors

    return reset_all_motors(
        plan,
        progress_callback=progress_callback,
        prompt_callback=prompt_callback,
        should_stop=should_stop,
    )

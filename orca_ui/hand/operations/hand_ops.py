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


def build_maintenance_hand(config, stop_event: threading.Event,
                           retry_s: float = 2.0, motor_port: str | None = None):
    """Fresh motor-only OrcaHand for a maintenance operation.

    Built from the supervisor's config, so the hardware version in force (and
    the joint map and travel features it selects) carries over. Always the
    plain class — never the feedback subclass, whose joint loop refuses to
    calibrate. Port-open is retried briefly to absorb the OS serial release
    latency after the supervisor closed the session.
    """
    import copy

    from orca_core import OrcaHand

    # A copy, so the port pin below never reaches the supervisor's config.
    hand = OrcaHand(config=copy.copy(config))
    if motor_port and getattr(hand.config, "port", None) == "auto":
        # The lease already resolved the motor port, scoped to the pinned
        # board when one is pinned; connect() must not look beyond it.
        object.__setattr__(hand.config, "port", motor_port)
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
    offset_deg: float | None = None,
    pull_more: Callable[[], bool] | None = None,
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
        **({} if offset_deg is None else {"offset_deg": offset_deg}),
        **({} if pull_more is None else {"pull_more": pull_more}),
    )


def guided_tension_supported() -> bool:
    try:
        import orca_core.maintenance.guided_tension  # noqa: F401
    except ImportError:
        return False
    return True


def guided_tension(hand, *, prompt_callback, progress_callback, should_stop,
                   hold_current=None, tension_current=None, tension_offset_deg=None,
                   pass_fraction=None,
                   hand_key: str | None = None, resume: bool = True,
                   any_hardware: bool = False) -> dict:
    """Blocking guided tensioning on the calling thread; prompts block on the operator.

    Settings left as None use orca_core's defaults; each may be a value or a
    callable (see run_guided_tension)."""
    from orca_core.maintenance.guided_tension import run_guided_tension

    settings = {k: v for k, v in (("hold_current", hold_current),
                                  ("tension_current", tension_current),
                                  ("tension_offset_deg", tension_offset_deg),
                                  ("pass_fraction", pass_fraction)) if v is not None}
    result = run_guided_tension(
        hand,
        prompt_callback=prompt_callback,
        progress_callback=progress_callback,
        should_stop=should_stop,
        hand_key=hand_key,
        resume=resume,
        any_hardware=any_hardware,
        **settings,
    )
    return {"completed": result.completed, "rounds": result.rounds}


def record_hold_tension(config) -> None:
    """Mark the hand tensioned after a plain hold-and-ratchet."""
    from orca_core.maintenance.guided_tension import record_hold_tension as record

    try:
        record(config)
    except Exception:
        logger.exception("recording the hold tension failed")


def range_stages() -> list[dict]:
    """orca_core's per-finger range-check stages (key, title, joints, pose)."""
    try:
        from orca_core.maintenance.guided_tension import DEFAULT_RANGE_STAGES
    except ImportError:
        return []
    return [stage.to_dict() for stage in DEFAULT_RANGE_STAGES]


def set_max_current(hand, current_ma: float) -> None:
    hand.set_max_current(current_ma)


def set_joint_currents(hand, current_for_joint) -> None:
    """Per-motor current limits from a joint name -> mA function (wrist excluded)."""
    from orca_core.maintenance.guided_tension import joint_currents, per_motor_currents

    hand.set_max_current(per_motor_currents(hand.config, joint_currents(hand.config, current_for_joint)))


def tension_progress(config, hand_key: str | None) -> dict | None:
    """Saved best score per joint for this hand's unfinished guided tensioning."""
    try:
        from orca_core.maintenance.guided_tension import read_progress
    except ImportError:
        return None
    try:
        return read_progress(config, hand_key)
    except Exception:
        logger.exception("reading the tension progress failed")
        return None


def last_tension(config) -> dict | None:
    """The last guided tension that reached 100 %, or None (or a core without it)."""
    try:
        from orca_core.maintenance.guided_tension import read_last_tension
    except ImportError:
        return None
    try:
        return read_last_tension(config)
    except Exception:
        logger.exception("reading the last tension record failed")
        return None


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


def detect_motor_type(port: str, progress_callback=None, chain_config: dict | None = None) -> str | None:
    """The family on ``port``: from a motor at factory defaults, else — given
    ``chain_config`` — from the configured chain that config describes."""
    from orca_core.maintenance.motor_chain import detect_motor_type as detect

    return detect(port, progress_callback=progress_callback, chain_config=chain_config)


def chain_config_mapping(config) -> dict:
    """The raw config mapping the motor-chain library works from."""
    return {
        "motor_ids": list(config.motor_ids),
        "joint_to_motor_map": dict(config.joint_to_motor_map or {}),
        "baudrate": getattr(config, "baudrate", None),
    }


def build_chain_plan(config, port: str, motor_type: str):
    """MotorChainPlan from an OrcaHandConfig (the library takes the raw
    config mapping)."""
    from orca_core.maintenance.motor_chain import plan_motor_chain

    return plan_motor_chain(
        chain_config_mapping(config),
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


def reset_motor(plan, motor: dict) -> bool:
    """Revert one motor, as scanned (id, baud_rate), to factory defaults."""
    from orca_core.maintenance.motor_chain import reset_motor_to_factory

    return reset_motor_to_factory(plan, motor["id"], motor["baud_rate"])


def reset_motors_once(plan, *, progress_callback, prompt_callback,
                      should_stop, all_rates: bool = False) -> list[dict]:
    """One reset pass over whatever is on the bus (the caller loops);
    ``all_rates`` also sweeps the baud rates hands never use."""
    from orca_core.maintenance.motor_chain import reset_all_motors

    return reset_all_motors(
        plan,
        progress_callback=progress_callback,
        prompt_callback=prompt_callback,
        all_rates=all_rates,
        should_stop=should_stop,
    )

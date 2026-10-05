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
                           retry_s: float = 2.0, motor_port: str | None = None):
    """Fresh motor-only OrcaHand for a maintenance operation.

    Always the plain class — never the feedback subclass, whose joint loop
    refuses to calibrate. Port-open is retried briefly to absorb the OS
    serial release latency after the supervisor closed the session.
    """
    from orca_core import OrcaHand

    hand = OrcaHand(config_path=config_path)
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


# ----- spooling (motor-level holds outside orca_core's routines) ----------------
#
# Spooling drives the motors itself from a tick loop, so these are the raw
# primitives it needs: direction convention, torque, current limits, one
# combined state read, and absolute target writes.


def read_motor_temps(hand) -> dict[int, float]:
    """One temperature per motor, in °C."""
    return {int(m): float(t)
            for m, t in hand.get_motor_temp(as_dict=True).items()}


def max_motor_temp_c(hand) -> float | None:
    """The family's rated operating ceiling, when the client declares one."""
    value = getattr(hand.motor_client, "max_operating_temp_c", None)
    return float(value) if value is not None else None


def enter_current_based_position(hand) -> None:
    from orca_core.constants import CURRENT_BASED_POSITION

    hand.set_control_mode(CURRENT_BASED_POSITION)


def restore_after_hold(hand) -> None:
    """What every hold must end with: configured current limit and control
    mode back, torque off."""
    hand.set_max_current(hand.config.max_current)
    hand.set_control_mode(hand.config.control_mode)
    hand.disable_torque()


def enable_torque(hand, motor_ids: list[int]) -> list[int]:
    """Returns the IDs that did not acknowledge."""
    return list(hand.enable_torque(motor_ids))


def set_current_limits(hand, limits: dict[int, float]) -> None:
    """Per-motor goal-current limits in mA; motors not named keep the
    configured ceiling."""
    default = float(hand.config.max_current)
    hand.set_max_current([float(limits.get(m, default))
                          for m in hand.config.motor_ids])


def read_motor_state(hand):
    """One bus transaction -> ({id: rad}, {id: mA}), or None when the read
    was stale (a stale sample must never drive a relative command)."""
    state = hand.get_motor_state()
    if not hand.last_read_ok:
        return None
    ids = hand.config.motor_ids
    positions = {m: float(p) for m, p in zip(ids, state.position)}
    currents = {m: float(c) for m, c in zip(ids, state.current)}
    return positions, currents


def write_motor_targets(hand, targets: dict[int, float]) -> None:
    import numpy as np

    if not targets:
        return
    ids = list(targets)
    hand.write_motor_pos(ids, np.array([targets[m] for m in ids], dtype=float))


def resolve_family_currents(config):
    """Config with ``default`` current limits replaced by the motor family's
    own — connect() does this on a real hand; the mock never connects."""
    if config.currents_resolved:
        return config
    from orca_core.hardware.motor_factory import motor_client_class

    return config.with_family_currents(
        motor_client_class(config.motor_type or "dynamixel"))


def motor_current_ceiling_ma(hand) -> float | None:
    """The hardware ceiling of the connected family's goal-current register."""
    value = getattr(hand.motor_client, "max_current_ma", None)
    return float(value) if value is not None else None


def read_servo_profiles(hand) -> dict:
    """Each motor's trajectory limits, to be handed back to
    :func:`restore_servo_profiles` afterwards."""
    return {m: p for m, p in hand.get_servo_profile().items() if p is not None}


def set_velocity_profile(hand, motor_ids: list[int], velocity_rad_s: float,
                         acceleration_rad_s2: float) -> None:
    """Cap how fast the named motors chase a goal, so a goal kept well ahead
    of the shaft becomes a smooth pull instead of a step."""
    from orca_core.hardware.motor_client import ServoProfile

    profile = ServoProfile(velocity_rad_s=velocity_rad_s,
                           acceleration_rad_s2=acceleration_rad_s2)
    hand.set_servo_profile({m: profile for m in motor_ids})


def restore_servo_profiles(hand, profiles: dict) -> None:
    if profiles:
        hand.set_servo_profile(profiles)

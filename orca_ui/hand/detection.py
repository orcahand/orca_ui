"""Hardware presence probing — which ports exist, before anything connects.

Wraps orca_core's detect_hand(): the OH board's identity reply names the
motor/sensing CDCs and the hand's side, a live encoder stream confirms joint
encoders, and a sensor register reply (or a dedicated adapter) confirms
tactile. Explicit port strings in the config pass through without opening
anything. All probes open ports exclusively and treat busy ports as absent,
so probing never disturbs a session we already hold.

Detection and port resolution are separate steps on purpose: one
:class:`~orca_core.HandDetection` can be re-read against a *different*
config, which is what lets the supervisor swap in the model the hardware
named without probing the bus a second time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from orca_core import HandDetection, detect_hand
from orca_core.hardware.sensing.constants import (
    DEFAULT_ENCODER_BAUDRATE,
    DEFAULT_SENSOR_BAUDRATE,
)
from orca_core.hardware.sensing.serial_discovery import SensingPorts
from orca_core.utils.utils import auto_detect_port

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwarePresence:
    motor_port: str | None
    sensing: SensingPorts
    detection: HandDetection | None = None
    """Full detection result (side, capabilities, identity) when discovery
    ran; None when every port was pinned in the config."""

    @property
    def any_present(self) -> bool:
        return bool(self.motor_port or self.sensing.tactile or self.sensing.encoder)

    @property
    def busy_ports(self) -> tuple[str, ...]:
        """Controller-board ports another process holds open. They probe as
        absent, so this is the difference between 'unplugged' and 'in use'."""
        return self.detection.busy_ports if self.detection is not None else ()


def _overrides(config) -> tuple[str, str, str]:
    """The config's (motor, tactile, encoder) port fields, normalized to
    ``"auto"`` (discover it), ``"disabled"`` (this hand has none) or an
    explicit device path."""
    motor = config.port if config.port not in ("auto", None) else "auto"
    tactile = getattr(config, "sensor_port", None) or "disabled"
    encoder = (
        config.encoder_serial_port if config.has_joint_encoders else "disabled"
    ) or "disabled"
    return motor, tactile, encoder


def names_a_hand(detection: HandDetection | None) -> bool:
    """True when a controller board actually answered.

    :func:`~orca_core.detect_hand` degrades to the plain right-hand model
    when nothing is plugged in, so ``model_name`` alone can't distinguish
    "this is a plain right hand" from "nothing is there". The identity reply
    can: it only exists when a board answered ``ORCA_INFO?``/``ORCA_ID?``.
    """
    return detection is not None and detection.identity is not None


def run_detection(config, *, force: bool = False) -> HandDetection | None:
    """Ask the hardware what it is, when anything still needs discovering.

    Skipped (returns None) when the config pins every port, since then
    nothing about the connection depends on the answer — unless ``force``,
    which callers use when they want the *model* the hardware reports rather
    than just its ports.
    """
    if not force and "auto" not in _overrides(config):
        return None
    try:
        return detect_hand()
    except Exception as e:
        # One line, no traceback: this runs on every reconnect attempt, and a
        # persistently unhappy serial stack would drown the log.
        logger.warning("hand detection failed: %s", e)
        return None


def presence_from_detection(config, detection: HandDetection | None
                            ) -> HardwarePresence:
    """Resolve the ports this config's declared capabilities need, reading a
    detection result that has already been taken.

    Explicit port strings in the config win over anything detected; only
    ``"auto"`` fields consume the detection. Passing a detection taken
    against another config is fine and deliberate — a detection describes the
    hardware, not the config it was requested for.
    """
    motor_override, tactile_override, encoder_override = _overrides(config)

    detected_tactile = None
    detected_encoder = None
    detected_baud = None
    if detection is not None:
        if detection.has_tactile:
            detected_tactile = detection.tactile_port or detection.sensing_port
            detected_baud = (
                DEFAULT_SENSOR_BAUDRATE if detection.tactile_port
                else DEFAULT_ENCODER_BAUDRATE
            )
        if detection.has_encoders:
            detected_encoder = detection.sensing_port

    if motor_override != "auto":
        motor_port = motor_override
    else:
        motor_port = detection.motor_port if detection is not None else None
        if motor_port is None:
            try:
                motor_port = auto_detect_port(config.motor_type)
            except Exception:
                motor_port = None

    def _field(override: str, detected: str | None) -> str | None:
        if override == "auto":
            return detected
        if override == "disabled":
            return None
        return override

    baud_override = getattr(config, "sensor_baudrate", "auto")
    sensing = SensingPorts(
        tactile=_field(tactile_override, detected_tactile),
        encoder=_field(encoder_override, detected_encoder),
        tactile_baudrate=(
            detected_baud if baud_override == "auto" else int(baud_override)
        ),
    )
    return HardwarePresence(motor_port=motor_port, sensing=sensing,
                            detection=detection)


def probe_hardware(config) -> HardwarePresence:
    """Detect and resolve in one step, for callers with no model to revise."""
    return presence_from_detection(config, run_detection(config))

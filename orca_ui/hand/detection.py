"""Hardware presence probing — which ports exist, before anything connects.

Wraps orca_core's detect_hand(): the OH board's identity reply names the
motor/sensing CDCs, a live encoder stream confirms joint encoders, and a
sensor register reply (or a dedicated adapter) confirms tactile. Explicit
port strings in the config pass through without opening anything. All
probes open ports exclusively and treat busy ports as absent, so probing
never disturbs a session we already hold.
"""

from __future__ import annotations

from dataclasses import dataclass

from orca_core import HandDetection, detect_hand
from orca_core.hardware.sensing.constants import (
    DEFAULT_ENCODER_BAUDRATE,
    DEFAULT_SENSOR_BAUDRATE,
)
from orca_core.hardware.sensing.serial_discovery import SensingPorts
from orca_core.utils.utils import auto_detect_port


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


def probe_hardware(config) -> HardwarePresence:
    """Probe for the ports this config's declared capabilities need.

    Explicit port strings in the config pass through without opening
    anything; only ``"auto"`` fields consume the detection result.
    """
    motor_override = config.port if config.port not in ("auto", None) else "auto"
    tactile_override = getattr(config, "sensor_port", None) or "disabled"
    encoder_override = (
        config.encoder_serial_port if config.has_joint_encoders else "disabled"
    ) or "disabled"

    detection: HandDetection | None = None
    if "auto" in (motor_override, tactile_override, encoder_override):
        try:
            detection = detect_hand()
        except Exception:
            detection = None

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
    return HardwarePresence(motor_port=motor_port, sensing=sensing, detection=detection)

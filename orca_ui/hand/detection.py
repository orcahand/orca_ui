"""Hardware presence probing — which ports exist, before anything connects.

Wraps orca_core's discovery: motor buses by USB VID (plus the ORCA_ID probe
that tells the OH board's two CDC ports apart) and the sensing ports
(tactile / encoder, possibly one shared link). All probes open ports
exclusively and treat busy ports as absent, so probing never disturbs a
session we already hold.
"""

from __future__ import annotations

from dataclasses import dataclass

from orca_core.hardware.sensing.serial_discovery import (
    SensingPorts,
    resolve_sensing_ports,
)
from orca_core.utils.utils import auto_detect_port


@dataclass(frozen=True)
class HardwarePresence:
    motor_port: str | None
    sensing: SensingPorts

    @property
    def any_present(self) -> bool:
        return bool(self.motor_port or self.sensing.tactile or self.sensing.encoder)


def probe_hardware(config) -> HardwarePresence:
    """Probe for the ports this config's declared capabilities need.

    Explicit port strings in the config pass through without opening
    anything; only ``"auto"`` fields trigger discovery.
    """
    try:
        motor_port = (
            config.port
            if config.port not in ("auto", None)
            else auto_detect_port(config.motor_type)
        )
    except Exception:
        motor_port = None

    tactile_override = getattr(config, "sensor_port", None) or "disabled"
    encoder_override = (
        config.encoder_serial_port if config.has_joint_encoders else "disabled"
    ) or "disabled"
    baud_override = getattr(config, "sensor_baudrate", "auto")

    try:
        sensing = resolve_sensing_ports(
            tactile_override=tactile_override,
            encoder_override=encoder_override,
            tactile_baud_override=baud_override,
        )
    except Exception:
        sensing = SensingPorts(tactile=None, encoder=None)

    return HardwarePresence(motor_port=motor_port, sensing=sensing)

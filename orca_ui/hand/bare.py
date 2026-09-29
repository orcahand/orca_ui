"""Bare motor mode: bring up loose motors that are not built into a hand.

A bench tool. Nothing here assumes a hand exists — no joints, no tendons, no
calibration, no sensing. The bus is scanned for whatever answers, and a config
is synthesised that describes exactly those motors, one pseudo-joint each, so
the rest of the console (direct motor sliders, per-motor faults, servo gains,
motor ID programming) works against it unchanged.

Scanning is ordered by what is likely rather than exhaustive: the rate the
hands run at, then the low end of the ID range. An ID nobody answers costs a
bus timeout, around 45 ms, so the default range settles in a second or two
while sweeping every ID at every rate takes over two minutes. Hence the sweep
is opt-in. Only Dynamixel could do better — its protocol can broadcast a ping
and collect every responder at once, where the Feetech protocol must ask each
ID in turn.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable

from orca_core.constants import (
    MOTOR_PORT_CLOSE_SETTLE_S,
    SUPPORTED_MOTOR_TYPES,
)
from orca_core.hardware.motor_factory import motor_client_class
from orca_core.maintenance.motor_chain import scan_motors
from orca_core.utils.utils import write_yaml_atomic

logger = logging.getLogger(__name__)

# The rate every packaged hand runs at, and the first one worth trying.
PREFERRED_BAUD = 1_000_000
# Motors are numbered from 1 up in every hand, and a factory-fresh servo
# answers at 1. Scanning past the twenties only pays off on a motor someone
# has deliberately programmed high, which is what --scan-all is for.
DEFAULT_ID_RANGE = (0, 25)
FULL_ID_RANGE = (0, 253)

# Fallback span for a family that declares no single-turn limit (Dynamixel is
# multi-turn, so its range is open). One revolution is what a bench test wants.
FALLBACK_ROM_DEG = (-360.0, 0.0)
# No calibration exists and nothing is known about what a motor is attached to,
# so the ceiling starts low enough to stall harmlessly against a finger.
BARE_MAX_CURRENT_MA = 150


def travel_span_deg(motor_type: str) -> tuple[float, float]:
    """The span a motor of this family can actually reach, in degrees.

    Taken from the client rather than assumed: Feetech's single turn lives
    entirely in negative radians, so a symmetric guess around zero maps to raw
    counts outside 0..4095. Those clamp to one end of travel, which on a
    torque-enabled motor means driving it into its stop.
    """
    span = motor_client_class(motor_type).position_range_rad
    if span is None:
        return FALLBACK_ROM_DEG
    lo, hi = (math.degrees(v) for v in span)
    return (round(lo, 3), round(hi, 3))


def pseudo_joint(motor_id: int) -> str:
    """Name for the one-to-one pseudo-joint standing in for ``motor_id``.

    Deliberately unlike a real joint name (``index_mcp``): anything reading
    these should be obviously looking at motor space, not hand space.
    """
    return f"motor_{motor_id:02d}"


@dataclass
class FoundMotor:
    motor_id: int
    baud_rate: int
    model_name: str
    motor_type: str


@dataclass
class BareScan:
    """What answered, and what was asked."""

    port: str
    motors: list[FoundMotor] = field(default_factory=list)
    # (motor_type, baud) pairs actually tried, for a report that distinguishes
    # "looked everywhere and found nothing" from "only looked at 1 Mbaud".
    probed: list[tuple[str, int]] = field(default_factory=list)
    id_range: tuple[int, int] = DEFAULT_ID_RANGE

    @property
    def motor_type(self) -> str | None:
        return self.motors[0].motor_type if self.motors else None

    @property
    def baud_rate(self) -> int | None:
        return self.motors[0].baud_rate if self.motors else None

    @property
    def motor_ids(self) -> list[int]:
        return sorted(m.motor_id for m in self.motors)

    @property
    def mixed_baud(self) -> bool:
        """Motors answering at two rates on one bus.

        Physically impossible on a shared line, so it means the scan was
        confused (an echo, a half-programmed motor) rather than that the bus
        really is split.
        """
        return len({m.baud_rate for m in self.motors}) > 1

    def as_dict(self) -> dict:
        return {
            "port": self.port,
            "motor_type": self.motor_type,
            "baud_rate": self.baud_rate,
            "id_range": list(self.id_range),
            "mixed_baud": self.mixed_baud,
            "probed": [{"motor_type": t, "baud_rate": b} for t, b in self.probed],
            "motors": [
                {
                    "id": m.motor_id,
                    "baud_rate": m.baud_rate,
                    "model_name": m.model_name,
                    "motor_type": m.motor_type,
                }
                for m in self.motors
            ],
        }


def _rates_for(motor_type: str, all_rates: bool) -> list[int]:
    """Rates to try for one family, the one the hands use first.

    Capped at :data:`PREFERRED_BAUD`: the families advertise rates well above
    it that nothing here runs, and scanning them costs the same as scanning a
    real one. Raise the cap when a hand actually uses a faster bus.
    """
    client = motor_client_class(motor_type)
    supported = [rate for rate in client.supported_baudrates()
                 if rate <= PREFERRED_BAUD]
    if not supported:
        return []
    if not all_rates:
        return [PREFERRED_BAUD] if PREFERRED_BAUD in supported else supported[:1]
    rest = [rate for rate in supported if rate != PREFERRED_BAUD]
    return ([PREFERRED_BAUD] if PREFERRED_BAUD in supported else []) + rest


def scan_bus(
    port: str,
    *,
    id_range: tuple[int, int] = DEFAULT_ID_RANGE,
    all_rates: bool = False,
    progress: Callable[[str, str, int], None] | None = None,
) -> BareScan:
    """Ping ``id_range`` on ``port`` for each family and rate until one answers.

    Stops at the first (family, rate) that finds anything: motors on one bus
    share a rate and speak one protocol, so a hit settles both questions and
    the remaining combinations cannot add a motor that is really there.
    """
    scan = BareScan(port=port, id_range=id_range)
    for motor_type in SUPPORTED_MOTOR_TYPES:
        for rate in _rates_for(motor_type, all_rates):
            if progress is not None:
                progress(motor_type, "scanning", rate)
            if scan.probed:
                # A USB serial port reopened too soon after a close answers
                # unreliably: back to back, a scan finds only part of the bus
                # and bare mode would silently list fewer motors than are
                # really there.
                time.sleep(MOTOR_PORT_CLOSE_SETTLE_S)
            scan.probed.append((motor_type, rate))
            try:
                found = scan_motors(motor_type, port, rate, id_range)
            except Exception:
                logger.debug("scan failed: %s @ %d baud", motor_type, rate,
                             exc_info=True)
                continue
            if not found:
                continue
            scan.motors = [
                FoundMotor(
                    motor_id=int(m["id"]),
                    baud_rate=int(m.get("baud_rate") or rate),
                    model_name=str(m.get("model_name") or "unknown"),
                    motor_type=motor_type,
                )
                for m in found
            ]
            scan.motors.sort(key=lambda m: m.motor_id)
            return scan
    return scan


def synthesize_config(scan: BareScan, *, side: str = "right") -> str:
    """Write a config describing exactly the motors that answered.

    One pseudo-joint per motor keeps the config valid — orca_core requires the
    motor, joint and joint-map counts to agree — without inventing a hand. The
    port, family and rate are pinned to what the scan resolved, so connecting
    re-probes nothing and cannot wander onto another adapter.
    """
    if not scan.motors:
        raise ValueError("no motors found: nothing to synthesise a config from")
    joints = [pseudo_joint(m.motor_id) for m in scan.motors]
    rom = travel_span_deg(scan.motor_type)
    config = {
        "port": scan.port,
        "motor_type": scan.motor_type,
        "baudrate": scan.baud_rate,
        "type": side,
        "control_mode": "current_based_position",
        "max_current": BARE_MAX_CURRENT_MA,
        "calibration_current": BARE_MAX_CURRENT_MA,
        "motor_ids": scan.motor_ids,
        "joint_ids": joints,
        "joint_to_motor_map": {
            pseudo_joint(m.motor_id): m.motor_id for m in scan.motors
        },
        # The reachable span, not a guess: a joint range the motor cannot
        # reach turns every command into a clamp against a hard stop.
        "joint_roms": {joint: list(rom) for joint in joints},
        # Mid-travel, which is reachable from anywhere and is never a stop.
        "neutral_position": {joint: round(sum(rom) / 2, 3) for joint in joints},
        # Nothing to calibrate: there is no hardstop to find on a loose motor.
        "calibration_sequence": [],
    }
    run_dir = os.path.join(tempfile.mkdtemp(prefix="orca_ui_bare_"), "bare-motors")
    os.makedirs(run_dir)
    path = os.path.join(run_dir, "config.yaml")
    write_yaml_atomic(path, config)
    return path


def describe(scan: BareScan) -> str:
    """One-line summary for the terminal banner."""
    if not scan.motors:
        rates = sorted({rate for _, rate in scan.probed})
        return (
            f"no motors answered on {scan.port} "
            f"(IDs {scan.id_range[0]}-{scan.id_range[1]}, "
            f"{', '.join(f'{r // 1000}k' for r in rates)} baud)"
        )

    ids = ", ".join(str(i) for i in scan.motor_ids)
    models = sorted({m.model_name for m in scan.motors})
    return (
        f"{len(scan.motors)} motor(s) on {scan.port}: IDs {ids} "
        f"({scan.motor_type} @ {scan.baud_rate} baud, {', '.join(models)})"
    )

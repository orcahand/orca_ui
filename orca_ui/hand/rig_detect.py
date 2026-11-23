"""Which board is the calibration rig (the turntable), and never the hand's.

The rig's controller board answers ORCA_ID? like a hand's (today's even claims
hand ser-3526), so the identity alone cannot tell. In order: a known rig USB
serial, or a rig flag in the board identity (config code RIG, serial rig-...).
Its motors never tell: the rig's motor models are hand motors too. Ports of the
hand (pinned board, live session, same USB device) are never rig candidates, and
a rig board is never offered or taken as a hand. docs/rig-dashboard.md.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

KNOWN_RIG_SERIALS = frozenset({
    "FC9578875154393741202020FF012940FC9578875154393741202020FF012940",   # rig v1 (claims hand ser-3526)
})
RIG_MODELS = ("XC430-T240BB-T", "XC430-W240-T", "XC330-T288-T")
RIG_CONFIG_CODES = frozenset({"RIG", "rig"})


@dataclass
class RigVerdict:
    rig: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


def rig_serials(*cfgs) -> frozenset[str]:
    """Known rig serials plus the ones the rig's yaml files pin (turntable.yaml, its calibration)."""
    out = set(KNOWN_RIG_SERIALS)
    for c in cfgs:
        s = ((c or {}).get("board") or {}).get("usb_serial")
        if s:
            out.add(str(s))
    return frozenset(out)


def identity_flags_rig(info) -> bool:
    if info is None:
        return False
    config, serial = getattr(info, "config", None), getattr(info, "serial", None) or ""
    return (config in RIG_CONFIG_CODES) or str(serial).lower().startswith("rig")


def classify(usb_serial: str | None, info=None, serials: Iterable[str] = KNOWN_RIG_SERIALS) -> RigVerdict:
    """Rig or not, from one board's USB serial and its ORCA identity."""
    claim = getattr(info, "serial", None) if info is not None else None
    if usb_serial and usb_serial in set(serials):
        w = [f"the rig board's ID claims hand {claim}: write a rig ID to it (config RIG, serial rig-<n>)"] \
            if claim and not identity_flags_rig(info) else []
        return RigVerdict(True, "known rig USB serial", w)
    if identity_flags_rig(info):
        return RigVerdict(True, "rig flag in the board ID")
    return RigVerdict(False, "")


def hand_ports(ports: Iterable[str | None], pinned: str | None) -> set[str]:
    """Every device path that belongs to the hand: its session's ports, the pinned board,
    and every port on the same USB device (both CDCs of one controller board)."""
    own = {p for p in (*ports, pinned) if p and p != "mock"}
    try:
        import serial.tools.list_ports
        listed = list(serial.tools.list_ports.comports())
    except Exception:
        return own
    serials = {p.serial_number for p in listed if p.device in own and p.serial_number}
    return own | {p.device for p in listed if p.serial_number and p.serial_number in serials}


def check_model(found: str | None, configured: str | None) -> list[str]:
    """Warnings for the rig motor read from the control table."""
    w = []
    if found and found not in RIG_MODELS:
        w.append(f"rig motor {found} is not a known rig model ({', '.join(RIG_MODELS)})")
    if found and configured and configured not in ("auto", found):
        w.append(f"turntable.yaml says {configured}, the control table says {found}")
    return w

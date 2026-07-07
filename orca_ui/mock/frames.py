"""Wire-format frame builders for the mock pumps (AA A9 encoder, AA 56 tactile).

Adapted from orca_core's test helpers, which don't ship in the wheel. Only
well-formed frames are needed here (malformed-frame forgery stays in
orca_core's tests).
"""

from __future__ import annotations

import numpy as np

from orca_core.hardware.sensing.constants import (
    AUTO_ENC_NUM_JOINTS,
    PROTOCOL_HEADER_AUTO,
    PROTOCOL_HEADER_AUTO_ENC,
    PROTOCOL_RESERVED,
)
from orca_core.hardware.sensing.framing import calculate_checksum


def set_even_parity(raw_counts: np.ndarray) -> np.ndarray:
    """Set bit 15 of each count so the 16-bit word has even popcount.

    The AS5048A sets an even-parity bit; ``parse_encoder_frame`` checks it,
    so mock frames must carry it for ``parity_ok`` to read all-true.
    """
    x = raw_counts.astype(np.uint16) & np.uint16(0x7FFF)
    parity = x.copy()
    for shift in (8, 4, 2, 1):
        parity ^= parity >> np.uint16(shift)
    parity &= np.uint16(1)
    return (x | (parity << np.uint16(15))).astype(np.uint16)


def make_encoder_frame(raw_counts: np.ndarray | None = None, error_byte: int = 0) -> bytes:
    """Build a wire-format AA A9 encoder frame."""
    if raw_counts is None:
        raw_counts = np.zeros(AUTO_ENC_NUM_JOINTS, dtype=np.uint16)
    payload = bytes([error_byte]) + raw_counts.astype("<u2").tobytes()
    body = (
        PROTOCOL_HEADER_AUTO_ENC
        + bytes([PROTOCOL_RESERVED])
        + len(payload).to_bytes(2, "little")
        + payload
    )
    return body + bytes([calculate_checksum(body)])


def wrap_tactile_auto_frame(valid_bytes: bytes, err_code: int = 0) -> bytes:
    """Wrap an encoded payload with the AA 56 envelope: header + meta + err + LRC."""
    payload = bytes([err_code]) + valid_bytes
    body = (
        PROTOCOL_HEADER_AUTO
        + bytes([PROTOCOL_RESERVED])
        + len(payload).to_bytes(2, "little")
        + payload
    )
    return body + bytes([calculate_checksum(body)])

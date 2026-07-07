"""Stateful AA 55 register responder for the mock tactile sensor.

Vendored from orca_core's test helpers (``tests/_tactile_helpers.py``, which
don't ship in the wheel) and extended to track the auto-stream arming state:
writes to the auto-data-type / auto-enable registers update
:class:`TactileMockState`, which the tactile pump reads to decide what frame
type (resultant / taxels / combined) to emit — mirroring how the real sensor
board only streams what the host armed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orca_core.constants import FINGER_NAMES
from orca_core.hardware.mock_hand_serial_link import MockHandSerialLink
from orca_core.hardware.sensing.constants import (
    ADDR_AUTO_DATA_TYPE,
    ADDR_AUTO_ENABLE,
    ADDR_CONNECTED_SENSORS_LENGTH,
    ADDR_CONNECTED_SENSORS_START,
    ADDR_NUM_TAXELS_LENGTH,
    ADDR_NUM_TAXELS_START,
    ADDR_RESULTANT_FORCE_START,
    BYTES_PER_RESULTANT,
    DEFAULT_FINGER_TO_SENSOR_ID,
    DEFAULT_TAXEL_COUNTS,
    FUNC_CODE_READ,
    FUNC_CODE_WRITE,
    PROTOCOL_HEADER_RESPONSE,
    PROTOCOL_RESERVED,
    RESULTANT_BLOCK_SIZE,
    SLOT_CONNECTED_BIT_POSITIONS,
    SLOT_DISTAL_TAXEL_REGISTER_OFFSETS,
)
from orca_core.hardware.sensing.framing import calculate_checksum
from orca_core.hardware.sensing.tactile_protocol import (
    _pack_resultant_for_mock,
    compute_distal_module_index,
    encode_auto_data_type,
)


@dataclass
class TactileMockState:
    """Mutable state behind the mock's AA 55 responses and stream arming."""

    connected_fingers: list[str] = field(default_factory=lambda: list(FINGER_NAMES))
    taxel_counts: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TAXEL_COUNTS))
    finger_to_sensor_id: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_FINGER_TO_SENSOR_ID)
    )
    resultant_forces: dict = field(default_factory=dict)

    # Stream arming, updated by register writes; read by the tactile pump.
    auto_resultant: bool = False
    auto_taxels: bool = False
    auto_enabled: bool = False

    @property
    def active_sensors(self) -> list[str]:
        """Connected fingers in slot-id order (matches wire-frame order)."""
        active = [f for f in FINGER_NAMES if f in self.connected_fingers]
        active.sort(key=lambda f: self.finger_to_sensor_id[f])
        return active


def install_tactile_mock(link: MockHandSerialLink, state: TactileMockState) -> None:
    """Wire a response provider that serves AA 55 reads/writes from ``state``."""
    link.set_response_provider(lambda request: _respond_to_request(request, state))


def _respond_to_request(request: bytes, state: TactileMockState) -> bytes | None:
    if len(request) < 9:
        return None
    func = request[3]
    address = int.from_bytes(request[4:6], "little")
    count = int.from_bytes(request[6:8], "little")

    if func == FUNC_CODE_READ:
        data = _read_register_value(address, count, state)
        return _build_read_response(address, data)
    if func == FUNC_CODE_WRITE:
        _apply_register_write(address, bytes(request[8:8 + count]), state)
        return _build_write_response(address)
    return None


def _apply_register_write(address: int, data: bytes, state: TactileMockState) -> None:
    if address == ADDR_AUTO_DATA_TYPE and data:
        from orca_core.hardware.sensing.tactile_protocol import decode_auto_data_type
        info = decode_auto_data_type(data[:1])
        state.auto_resultant = info["resultant"]
        state.auto_taxels = info["taxels"]
    elif address == ADDR_AUTO_ENABLE and data:
        state.auto_enabled = data[0] == 0x01


def _read_register_value(address: int, count: int, state: TactileMockState) -> bytes:
    if address == ADDR_CONNECTED_SENSORS_START:
        block = _encode_connected_sensors(state)
    elif address == ADDR_NUM_TAXELS_START:
        block = _encode_num_taxels(state)
    elif address == ADDR_RESULTANT_FORCE_START:
        block = _encode_resultant_register_block(state)
    elif address == ADDR_AUTO_DATA_TYPE:
        block = encode_auto_data_type(state.auto_resultant, state.auto_taxels)
    elif address == ADDR_AUTO_ENABLE:
        block = bytes([0x01 if state.auto_enabled else 0x00])
    else:
        block = b"\x00" * count
    if len(block) >= count:
        return block[:count]
    return block + b"\x00" * (count - len(block))


def _encode_connected_sensors(state: TactileMockState) -> bytes:
    out = bytearray(ADDR_CONNECTED_SENSORS_LENGTH)
    for finger in state.connected_fingers:
        slot = state.finger_to_sensor_id[finger]
        byte_idx, bit_pos = SLOT_CONNECTED_BIT_POSITIONS[slot]
        out[byte_idx] |= 1 << bit_pos
    return bytes(out)


def _encode_num_taxels(state: TactileMockState) -> bytes:
    out = bytearray(ADDR_NUM_TAXELS_LENGTH)
    for finger in state.connected_fingers:
        slot = state.finger_to_sensor_id[finger]
        addr = SLOT_DISTAL_TAXEL_REGISTER_OFFSETS[slot]
        offset = addr - ADDR_NUM_TAXELS_START
        count = state.taxel_counts.get(finger, 0)
        out[offset:offset + 2] = count.to_bytes(2, "little")
    return bytes(out)


def _encode_resultant_register_block(state: TactileMockState) -> bytes:
    out = bytearray(RESULTANT_BLOCK_SIZE)
    for finger, force in state.resultant_forces.items():
        slot = state.finger_to_sensor_id[finger]
        module_idx = compute_distal_module_index(slot)
        offset = module_idx * BYTES_PER_RESULTANT
        out[offset:offset + BYTES_PER_RESULTANT] = _pack_resultant_for_mock(force)
    return bytes(out)


def _build_read_response(address: int, data: bytes) -> bytes:
    body = (
        PROTOCOL_HEADER_RESPONSE
        + bytes([PROTOCOL_RESERVED, FUNC_CODE_READ])
        + address.to_bytes(2, "little")
        + len(data).to_bytes(2, "little")
        + data
    )
    return body + bytes([calculate_checksum(body)])


def _build_write_response(address: int) -> bytes:
    payload = bytes([0x00])  # status byte: 0 = success
    body = (
        PROTOCOL_HEADER_RESPONSE
        + bytes([PROTOCOL_RESERVED, FUNC_CODE_WRITE])
        + address.to_bytes(2, "little")
        + len(payload).to_bytes(2, "little")
        + payload
    )
    return body + bytes([calculate_checksum(body)])

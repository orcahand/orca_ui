"""Background threads feeding wire frames into the mock serial links.

``EncoderPump`` synthesizes AA A9 frames from the *mock motor positions*, so
the joint-feedback loop genuinely closes in --mock: commanding a joint moves
the mock motors, the pump reflects them as encoder counts, and
``get_measured_joints()`` converges on the target.

``TactilePump`` emits AA 56 frames built from the sine providers, honoring
the arming state the tactile client wrote to the mock registers (resultant /
taxels / combined, enabled or not).
"""

from __future__ import annotations

import threading
import time

import numpy as np

from orca_core.hardware.mock_hand_serial_link import MockHandSerialLink
from orca_core.hardware.sensing.constants import (
    AUTO_ENC_NUM_JOINTS,
    ENCODER_COUNTS_PER_REV,
    ENCODER_LSB_DEG,
    JOINT_ENCODER_POLARITY,
    JOINT_TO_ENCODER_SLOT,
)
from orca_core.hardware.sensing.tactile_protocol import (
    encode_combined_auto_for_mock,
    encode_resultant_auto_for_mock,
    encode_taxels_auto_for_mock,
)

from orca_ui.mock.frames import make_encoder_frame, set_even_parity, wrap_tactile_auto_frame
from orca_ui.mock.signals import make_sine_providers
from orca_ui.mock.tactile_responder import TactileMockState

ENCODER_PUMP_PERIOD_S = 0.005   # 200 Hz, 10x margin on the loop's 50 ms watchdog
TACTILE_PUMP_PERIOD_S = 0.012   # ~83 Hz, the real sensor's output rate

# The mock motor client teleports to commanded positions. A zero-lag plant
# behind a one-cycle measurement delay makes the PI loop (Kp=1) marginally
# unstable, which real hardware never is — the tendon/joint follows the motor
# with lag. Model that: the pump's simulated joint angle approaches the
# motor-implied angle as a first-order lag with this time constant.
JOINT_LAG_TAU_S = 0.04


class _Pump(threading.Thread):
    def __init__(self, name: str):
        super().__init__(name=name, daemon=True)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=1.0)


class EncoderPump(_Pump):
    """Feed AA A9 frames whose counts mirror the mock motor positions."""

    def __init__(self, link: MockHandSerialLink, hand):
        super().__init__("MockEncoderPump")
        self._link = link
        self._hand = hand
        self._sim_deg: dict[str, float] = {}

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._link.feed_bytes(make_encoder_frame(self._counts()))
            except Exception:
                return  # link torn down mid-feed: pump's job is over
            time.sleep(ENCODER_PUMP_PERIOD_S)

    def _lagged_joints(self) -> dict:
        """Motor-implied joint angles, run through the first-order joint lag."""
        actual = self._hand._motor_to_joint_pos(self._hand.get_motor_pos())
        alpha = ENCODER_PUMP_PERIOD_S / JOINT_LAG_TAU_S
        for joint, deg in actual.items():
            if deg is None:
                continue
            prev = self._sim_deg.get(joint)
            self._sim_deg[joint] = deg if prev is None else prev + alpha * (deg - prev)
        return self._sim_deg

    def _counts(self) -> np.ndarray:
        joints = self._lagged_joints()
        counts = np.zeros(AUTO_ENC_NUM_JOINTS, dtype=np.uint16)
        enc_cal = self._hand.calibration.joint_encoder_calibration_dict
        roms = self._hand.config.joint_roms_dict
        for joint, cal in enc_cal.items():
            slot = JOINT_TO_ENCODER_SLOT.get(joint)
            deg = joints.get(joint)
            if slot is None or deg is None:
                continue
            # Invert encoder_to_joint_angle: the anchor angle is the ROM upper
            # (the pose the real calibration sweep stalls the motor at).
            anchor_angle = roms[joint][1]
            polarity = JOINT_ENCODER_POLARITY[joint]
            count = round(
                cal.enc_at_anchor_count + polarity * (deg - anchor_angle) / ENCODER_LSB_DEG
            )
            counts[slot] = count % ENCODER_COUNTS_PER_REV
        return set_even_parity(counts)


class TactilePump(_Pump):
    """Feed AA 56 frames from the sine providers, per the armed stream mode."""

    def __init__(self, link: MockHandSerialLink, state: TactileMockState):
        super().__init__("MockTactilePump")
        self._link = link
        self._state = state
        self._resultant_provider, self._taxel_provider = make_sine_providers()

    def run(self) -> None:
        while not self._stop_event.is_set():
            state = self._state
            if state.auto_enabled:
                try:
                    frame = self._build_frame(state)
                    if frame is not None:
                        self._link.feed_bytes(frame)
                except Exception:
                    return
            time.sleep(TACTILE_PUMP_PERIOD_S)

    def _build_frame(self, state: TactileMockState) -> bytes | None:
        active = state.active_sensors
        if not active:
            return None
        if state.auto_resultant and state.auto_taxels:
            valid = encode_combined_auto_for_mock(
                self._resultant_provider(), self._taxel_provider(), active)
        elif state.auto_resultant:
            valid = encode_resultant_auto_for_mock(self._resultant_provider(), active)
        elif state.auto_taxels:
            valid = encode_taxels_auto_for_mock(self._taxel_provider(), active)
        else:
            return None
        return wrap_tactile_auto_frame(valid)

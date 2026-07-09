"""Mock hand classes wired with responders and frame pumps.

orca_core's ``Mock*`` hands swap serial I/O for :class:`MockHandSerialLink`
but feed it nothing; these subclasses instrument the link-creation seams so
the production clients see live register responses and streaming frames.
Class selection mirrors ``orca_core.hand_factory`` (tactile from the
``sensors:`` block, feedback from ``joint_feedback_enabled``).
"""

from __future__ import annotations

from orca_core.hand_config import OrcaHandConfig, OrcaHandTouchConfig
from orca_core.hardware.mock_hand_serial_link import MockHandSerialLink
from orca_core import (
    MockOrcaHand,
    MockOrcaHandFull,
    MockOrcaHandJointFeedback,
    MockOrcaHandTouch,
)
from orca_core.utils.utils import read_yaml

from orca_ui.mock.pumps import EncoderPump, TactilePump
from orca_ui.mock.tactile_responder import TactileMockState, install_tactile_mock


class _PumpOwner:
    """Owns pump lifecycles; ``disconnect()`` stops them before link teardown."""

    def _pumps(self) -> list:
        if not hasattr(self, "_mock_pumps"):
            self._mock_pumps = []
        return self._mock_pumps

    def _start_pump(self, pump) -> None:
        self._pumps().append(pump)
        pump.start()

    def disconnect(self):
        for pump in self._pumps():
            pump.stop()
        self._pumps().clear()
        return super().disconnect()

    # -- shared instrumentation ------------------------------------------

    def _instrument_tactile(self, link: MockHandSerialLink) -> None:
        state = TactileMockState(
            finger_to_sensor_id=dict(self.config.finger_to_sensor_id),
        )
        install_tactile_mock(link, state)
        self._start_pump(TactilePump(link, state))

    def _instrument_encoders(self, link: MockHandSerialLink) -> None:
        self._start_pump(EncoderPump(link, self))


class UiMockOrcaHand(_PumpOwner, MockOrcaHand):
    """Motors only — nothing to pump."""


class UiMockOrcaHandTouch(_PumpOwner, MockOrcaHandTouch):
    def _create_tactile_link(self, port: str, baudrate: int) -> MockHandSerialLink:
        link = super()._create_tactile_link(port, baudrate)
        self._instrument_tactile(link)
        return link


class UiMockOrcaHandJointFeedback(_PumpOwner, MockOrcaHandJointFeedback):
    def _create_encoder_link(self, port: str) -> MockHandSerialLink:
        link = super()._create_encoder_link(port)
        self._instrument_encoders(link)
        return link


class UiMockOrcaHandFull(_PumpOwner, MockOrcaHandFull):
    """Both streams. With the bundled mock model the ports are equal, so the
    encoder link is shared and carries tactile too; the dedicated-tactile-port
    seam is instrumented as well for custom configs."""

    def _create_encoder_link(self, port: str) -> MockHandSerialLink:
        link = super()._create_encoder_link(port)
        self._instrument_encoders(link)
        self._instrument_tactile(link)
        return link

    def _create_tactile_link(self, port: str, baudrate: int) -> MockHandSerialLink:
        link = super()._create_tactile_link(port, baudrate)
        self._instrument_tactile(link)
        return link


# (feedback, tactile) -> class; mirrors orca_core.hand_factory._CLASS_MATRIX.
_UI_MOCK_MATRIX = {
    (False, False): UiMockOrcaHand,
    (False, True): UiMockOrcaHandTouch,
    (True, False): UiMockOrcaHandJointFeedback,
    (True, True): UiMockOrcaHandFull,
}


# Synthetic mock calibration: motor = joint_deg * RATIO (sign-flipped for
# inverted joints), so 0 rad on the mock motors is exactly 0 deg on every
# joint and all limits fit MockDynamixelClient's +/-1 rad clamp.
_MOCK_RATIO_RAD_PER_DEG = 0.005
_MOCK_ANCHOR_COUNT = 8192


def _synthetic_calibration(hand) -> None:
    """Replace the hand's loaded calibration with mock-consistent values.

    A real model's calibration describes real motors (limits at arbitrary
    shaft positions); pushing the mock motors' 0-rad start through it yields
    angles far outside every ROM — the hand renders as a contorted claw and
    nothing converges. Mock simulates the *declared* hand instead.
    """
    import dataclasses

    from orca_core.calibration import JointEncoderCal
    from orca_core.hardware.sensing.constants import JOINT_TO_ENCODER_SLOT

    config = hand.config
    motor_limits: dict = {}
    ratios: dict = {}
    for joint, motor_id in config.joint_to_motor_map.items():
        # joint_to_motor_map is canonicalized (always-positive ids); the
        # sign information lives in joint_inversion_dict.
        inverted = config.joint_inversion_dict.get(joint, False)
        motor_id = abs(motor_id)
        rom_lo, rom_hi = config.joint_roms_dict[joint]
        if inverted:
            limits = [-rom_hi * _MOCK_RATIO_RAD_PER_DEG,
                      -rom_lo * _MOCK_RATIO_RAD_PER_DEG]
        else:
            limits = [rom_lo * _MOCK_RATIO_RAD_PER_DEG,
                      rom_hi * _MOCK_RATIO_RAD_PER_DEG]
        motor_limits[motor_id] = limits
        ratios[motor_id] = _MOCK_RATIO_RAD_PER_DEG

    configured = config.joint_encoder_joints or []
    select_all = any(str(j).lower() == "all" for j in configured)
    encoder_cal = {
        joint: JointEncoderCal(enc_at_anchor_count=_MOCK_ANCHOR_COUNT)
        for joint in JOINT_TO_ENCODER_SLOT
        if joint in config.joint_to_motor_map
        and (select_all or joint in configured or joint == "wrist")
    }

    hand.calibration = dataclasses.replace(
        hand.calibration,
        motor_limits_dict=motor_limits,
        joint_to_motor_ratios_dict=ratios,
        joint_encoder_calibration_dict=encoder_cal,
        calibrated=True,
        wrist_calibrated=True,
    )


def build_mock_hand(config_path: str, engage_feedback: bool = True):
    """Construct the instrumented mock hand matching the config's capabilities.

    Two isolations from the real world, whatever the config says:

    * Ports are forced to fixed mock values — a real config typically
      declares ``auto``, and mock mode must never probe (or open) real
      hardware that happens to be plugged in.
    * Calibration is synthesized from the config's ROMs and writes go to a
      throwaway directory — a real hand's calibration is meaningless for the
      in-memory motors, and zeroing from the UI must not dirty real model
      folders.
    """
    import dataclasses
    import os
    import tempfile

    raw = read_yaml(config_path) or {}
    tactile = "sensors" in raw
    config_cls = OrcaHandTouchConfig if tactile else OrcaHandConfig
    config = config_cls.from_config_path(config_path=config_path)

    scratch_dir = tempfile.mkdtemp(prefix="orca_ui_mock_cal_")
    scratch_calibration = os.path.join(scratch_dir, "calibration.yaml")
    with open(scratch_calibration, "w") as f:
        f.write("calibrated: false\n")

    overrides: dict = {
        "port": "mock",
        "encoder_serial_port": "/dev/orca-mock",
        "calibration_path": scratch_calibration,
    }
    if tactile:
        overrides["sensor_port"] = "/dev/orca-mock"  # == encoder -> shared link
        overrides["sensor_baudrate"] = 2_000_000     # explicit -> no baud probe
    config = dataclasses.replace(config, **overrides)

    feedback = engage_feedback and config.joint_feedback_enabled
    hand = _UI_MOCK_MATRIX[(bool(feedback), tactile)](config=config)
    _synthetic_calibration(hand)
    return hand

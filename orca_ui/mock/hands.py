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
from orca_core.hardware_hand import MockOrcaHand, MockOrcaHandTouch
from orca_core.hardware_hand_joint_feedback import (
    MockOrcaHandFull,
    MockOrcaHandJointFeedback,
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


def build_mock_hand(config_path: str, engage_feedback: bool = True):
    """Construct the instrumented mock hand matching the config's capabilities."""
    raw = read_yaml(config_path) or {}
    tactile = "sensors" in raw
    config_cls = OrcaHandTouchConfig if tactile else OrcaHandConfig
    config = config_cls.from_config_path(config_path=config_path)
    feedback = engage_feedback and config.joint_feedback_enabled
    return _UI_MOCK_MATRIX[(bool(feedback), tactile)](config=config)

"""Connected-hand sessions: one object per successful connection attempt.

A session wraps whatever actually connected — a full hand, a degraded subset,
or sensors with no motor power — behind capability-routed accessors, so the
telemetry/service layers never care which tier they got.

``connect_session`` owns the degradation ladder:

  motors + declared caps present  ->  load_hand tier (full / feedback / touch / motors)
  motors absent, sensors present  ->  sensors-only session (tactile and/or
                                      encoder viewing; no motor control)

Feedback/full connects are all-or-nothing in orca_core (rollback + raise), so
each rung constructs a *fresh* hand and tries again with less.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from orca_core import load_hand
from orca_core.hand_config import OrcaHandTouchConfig
from orca_core.hardware.hand_serial_link import HandSerialLink
from orca_core.hardware.joint_encoder_client import (
    EncodersNotAvailableError,
    JointEncoderClient,
)
from orca_core.hardware_hand import OrcaHand
from orca_core.hardware_hand_joint_feedback import (
    JointFeedbackConnectError,
    OrcaHandJointFeedback,
)

from orca_ui.hand.detection import HardwarePresence, probe_hardware
from orca_ui.hand.states import Capabilities
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)


class SessionConnectError(RuntimeError):
    """No tier connected. ``attempts`` lists per-tier failure messages."""

    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def declared_capabilities(config, engage_feedback: bool) -> dict:
    return {
        "motors": True,
        "tactile": isinstance(config, OrcaHandTouchConfig),
        "encoders": bool(config.has_joint_encoders),
        "feedback_loop": bool(engage_feedback and config.joint_feedback_enabled),
    }


@dataclass
class HandSession:
    """A live connection at some capability tier. Thread-safety comes from
    orca_core (motor lock, client locks); accessors here only route."""

    hand: OrcaHand
    caps: Capabilities
    tier: str
    message: str
    ports: dict = field(default_factory=dict)
    # Sensor-only extras (owned only when the hand object isn't connected):
    _owned_links: list = field(default_factory=list)
    _encoder_client: JointEncoderClient | None = None
    _estimate_ok: bool | None = None  # lazily: is the motor calibration usable?

    # ----- tactile ---------------------------------------------------------

    @property
    def tactile_client(self):
        return getattr(self.hand, "_tactile_client", None)

    def start_tactile_stream(self, resultant: bool, taxels: bool) -> None:
        self.tactile_client.start_stream(resultant=resultant, taxels=taxels)

    def stop_tactile_stream(self) -> None:
        if self.tactile_client is not None:
            self.tactile_client.stop_stream()

    def tactile_data(self):
        tc = self.tactile_client
        return tc.get_latest() if tc else None

    def tactile_configuration(self):
        tc = self.tactile_client
        return tc.get_tactile_configuration() if tc else None

    def tactile_stats(self):
        tc = self.tactile_client
        return tc.get_stats() if tc else None

    # ----- joints ----------------------------------------------------------

    def measured_joints(self) -> dict | None:
        """Encoder-measured joint angles in degrees, or None.

        Decodes the raw encoder frame directly (same math the loop uses)
        rather than asking the loop, because the loop only tracks its
        closed-loop joints — the wrist encoder (slot 16) is sensed but
        deliberately outside the loop, and it must still be reported here.
        Covers every joint with a ``joint_encoder_calibration`` entry.
        """
        client = self._encoder_client or getattr(self.hand, "_encoder_client", None)
        if client is None:
            return None
        reading = client.get_latest()
        if reading is None:
            return None
        return self.hand._raw_to_joint_angle(reading.raw_counts)

    def estimate_joints(self) -> dict | None:
        """Naive motor-derived joint angles in degrees (the 'ghost' pose)."""
        if not self.caps.motors:
            return None
        if self._estimate_ok is None:
            # _motor_to_joint_pos prints per-joint warnings on uncalibrated
            # hands; check once instead of spamming at the sampler rate.
            try:
                self._estimate_ok = bool(self.hand.is_calibrated())
            except Exception:
                self._estimate_ok = False
            if not self._estimate_ok:
                logger.warning(
                    "motor calibration incomplete — joint estimate disabled "
                    "(run orca_core's calibration first)")
        if not self._estimate_ok:
            return None
        pos = self.hand._motor_to_joint_pos(self.hand.get_motor_pos())
        return {j: v for j, v in pos.items() if v is not None}

    def loop_correction(self) -> dict | None:
        return self.hand.get_loop_correction() if self.caps.feedback_loop else None

    def loop_stats(self) -> dict | None:
        return self.hand.get_loop_stats() if self.caps.feedback_loop else None

    def encoder_stats(self):
        client = self._encoder_client or getattr(self.hand, "_encoder_client", None)
        return client.get_stats() if client else None

    # ----- lifecycle -------------------------------------------------------

    def close(self) -> None:
        if self._encoder_client is not None:
            try:
                self._encoder_client.disconnect()
            except Exception:
                pass
        try:
            # All hand classes tolerate partial state; for sensors-only
            # sessions this also tears down the tactile link opened by
            # connect_sensors_only().
            self.hand.disconnect()
        except Exception:
            logger.exception("hand disconnect failed during session close")
        for link in self._owned_links:
            try:
                link.disconnect()
            except Exception:
                pass
        self._owned_links.clear()


# ---------------------------------------------------------------------------
# Connection ladder
# ---------------------------------------------------------------------------


def connect_session(settings: UiSettings, config) -> HandSession:
    """Probe hardware and connect at the best achievable tier."""
    declared = declared_capabilities(config, settings.engage_feedback)

    if settings.mock:
        return _connect_mock(settings, declared)

    presence = probe_hardware(config)
    if presence.motor_port:
        return _connect_with_motors(settings, config, declared, presence)
    if presence.sensing.tactile or presence.sensing.encoder:
        return _connect_sensors_only(settings, config, declared, presence)
    raise SessionConnectError(
        "No ORCA hardware found (no motor bus, tactile, or encoder port)."
    )


def _caps_from_hand(hand, declared: dict) -> Capabilities:
    feedback = isinstance(hand, OrcaHandJointFeedback) and hand._loop is not None
    return Capabilities(
        motors=hand.is_connected(),
        tactile=getattr(hand, "_tactile_client", None) is not None,
        encoders=feedback,
        feedback_loop=feedback,
        declared=declared,
    )


def _connect_mock(settings: UiSettings, declared: dict) -> HandSession:
    from orca_ui.mock import build_mock_hand

    # Mirror the real ladder's key degradation: a config whose encoder
    # calibration is incomplete (JointFeedbackConnectError) still connects
    # open-loop, so real configs can be previewed in --mock as they would
    # behave on hardware.
    attempts: list[str] = []
    for engage_feedback, tier in ((settings.engage_feedback, "mock"),
                                  (False, "mock-open-loop")):
        hand = build_mock_hand(settings.config_path,
                               engage_feedback=engage_feedback)
        try:
            ok, msg = hand.connect()
        except (JointFeedbackConnectError, RuntimeError) as e:
            attempts.append(f"{tier}: {e}")
            continue
        if not ok:
            attempts.append(f"{tier}: {msg}")
            continue
        return HandSession(
            hand=hand,
            caps=_caps_from_hand(hand, declared),
            tier=tier,
            message=msg,
            ports={"motor": "mock", "tactile": "mock", "encoder": "mock"},
        )
    raise SessionConnectError("mock connect failed", attempts=attempts)


def _build_hand(settings: UiSettings, config, feedback: bool, tactile: bool):
    """Fresh hand instance for one ladder rung (never reuse across attempts)."""
    if feedback and not tactile and isinstance(config, OrcaHandTouchConfig):
        # No factory entry for 'feedback hand from a touch config': construct
        # directly; OrcaHandJointFeedback ignores the sensors block.
        return OrcaHandJointFeedback(config=config)
    if not feedback and not tactile and isinstance(config, OrcaHandTouchConfig):
        return OrcaHand(config=config)
    return load_hand(config_path=settings.config_path,
                     engage_feedback=feedback)


def _connect_with_motors(settings, config, declared, presence: HardwarePresence):
    want_feedback = declared["feedback_loop"] and bool(presence.sensing.encoder)
    want_tactile = declared["tactile"] and bool(presence.sensing.tactile)

    ladder: list[tuple[bool, bool]] = []
    for rung in [(want_feedback, want_tactile), (want_feedback, False),
                 (False, want_tactile), (False, False)]:
        if rung not in ladder:
            ladder.append(rung)

    ports = {
        "motor": presence.motor_port,
        "tactile": presence.sensing.tactile,
        "encoder": presence.sensing.encoder,
    }
    attempts: list[str] = []
    for feedback, tactile in ladder:
        tier = _tier_name(feedback, tactile)
        hand = _build_hand(settings, config, feedback, tactile)
        try:
            ok, msg = hand.connect()
        except (JointFeedbackConnectError, RuntimeError) as e:
            attempts.append(f"{tier}: {e}")
            logger.warning("connect tier %s failed: %s", tier, e)
            continue
        if ok:
            return HandSession(hand=hand, caps=_caps_from_hand(hand, declared),
                               tier=tier, message=msg, ports=ports)
        # OrcaHandTouch.connect leaves the motor bus up when only the sensor
        # failed — that IS the motors(-only or +feedback) tier, keep it.
        if hand.is_connected():
            logger.warning("connect tier %s partial: %s", tier, msg)
            return HandSession(hand=hand, caps=_caps_from_hand(hand, declared),
                               tier=_tier_name(feedback, False),
                               message=msg, ports=ports)
        attempts.append(f"{tier}: {msg}")
        logger.warning("connect tier %s failed: %s", tier, msg)

    raise SessionConnectError("all connect tiers failed", attempts=attempts)


def _tier_name(feedback: bool, tactile: bool) -> str:
    return {
        (True, True): "full",
        (True, False): "feedback",
        (False, True): "touch",
        (False, False): "motors",
    }[(feedback, tactile)]


def _connect_sensors_only(settings, config, declared, presence: HardwarePresence):
    """Motors unpowered: tactile viewing and/or encoder viewing only."""
    hand = load_hand(config_path=settings.config_path, engage_feedback=False)
    ports = {"motor": None, "tactile": None, "encoder": None}
    messages: list[str] = []
    owned_links: list[HandSerialLink] = []
    tactile_ok = False

    if declared["tactile"] and presence.sensing.tactile:
        ok, msg = hand.connect_sensors_only()
        messages.append(msg)
        tactile_ok = ok
        if ok:
            ports["tactile"] = hand.config.sensor_port

    encoder_client = None
    if declared["encoders"] and presence.sensing.encoder:
        if hand.calibration.joint_encoder_calibration_dict:
            try:
                shared_link = (
                    hand._tactile_link
                    if tactile_ok and presence.sensing.shared
                    else None
                )
                if shared_link is not None:
                    enc_link = shared_link
                else:
                    enc_link = HandSerialLink(
                        port=presence.sensing.encoder,
                        baudrate=config.encoder_baudrate,
                    )
                    enc_link.connect()
                    owned_links.append(enc_link)
                encoder_client = JointEncoderClient(enc_link)
                encoder_client.connect()
                encoder_client.start_stream()
                ports["encoder"] = presence.sensing.encoder
                messages.append(f"Encoder stream on {presence.sensing.encoder}")
            except Exception as e:  # includes EncodersNotAvailableError
                logger.warning("encoder-only attach failed: %s", e)
                messages.append(f"encoders unavailable: {e}")
                encoder_client = None
                for link in owned_links:
                    try:
                        link.disconnect()
                    except Exception:
                        pass
                owned_links = []
        else:
            messages.append("encoders present but no joint_encoder_calibration")

    if not tactile_ok and encoder_client is None:
        raise SessionConnectError(
            "sensors detected but neither stream connected: "
            + " | ".join(messages)
        )

    caps = Capabilities(
        motors=False,
        tactile=tactile_ok,
        encoders=encoder_client is not None,
        feedback_loop=False,
        declared=declared,
    )
    return HandSession(
        hand=hand, caps=caps, tier="sensors-only",
        message=" | ".join(messages), ports=ports,
        _owned_links=owned_links, _encoder_client=encoder_client,
    )

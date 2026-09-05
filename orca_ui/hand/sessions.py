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
from orca_core.hardware.sensing.types import LinkHealth
from orca_core import JointFeedbackConnectError, OrcaHand, OrcaHandJointFeedback

from orca_ui.hand.detection import HardwarePresence, probe_hardware
from orca_ui.hand.states import Capabilities
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)


class SessionConnectError(RuntimeError):
    """No tier connected. ``attempts`` lists per-tier failure messages."""

    def __init__(self, message: str, attempts: list[str] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


def declared_capabilities(config, engage_feedback: bool,
                          motors_enabled: bool = True) -> dict:
    return {
        "motors": motors_enabled,
        "tactile": isinstance(config, OrcaHandTouchConfig),
        "encoders": bool(config.has_joint_encoders),
        "feedback_loop": bool(motors_enabled and engage_feedback
                              and config.joint_feedback_enabled),
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
        rather than asking the loop, because the loop only tracks the joints
        it closes on — a joint skipped at connect is still sensed, and it
        must still be reported here. Covers every joint with a
        ``joint_encoder_calibration`` entry.
        """
        client = self._encoder_client or getattr(self.hand, "_encoder_client", None)
        if client is None:
            return None
        reading = client.get_latest()
        if reading is None:
            return None
        return self.hand._raw_to_joint_angle(reading.raw_counts)

    def joint_source(self) -> "str | None":
        """Where sampled joint angles come from: ``"encoders"`` for measured
        angles, ``"motors"`` for the calibrated motor-derived estimate, or
        ``None`` when the session has neither."""
        if self.caps.encoders:
            return "encoders"
        if self.caps.motors and self._estimate_allowed():
            return "motors"
        return None

    def sampled_joints(self) -> dict | None:
        """Joint angles for recording and pose capture, or ``None``.

        Encoder-measured when the hand has encoders, otherwise the
        calibrated motor estimate from a single bus read."""
        if self.caps.encoders:
            return self.measured_joints()
        if self.caps.motors and self._estimate_allowed():
            return self._joint_estimate(self.hand.get_motor_state().position)
        return None

    def _estimate_allowed(self) -> bool:
        if self._estimate_ok is None:
            # _motor_to_joint_pos prints per-joint warnings on uncalibrated
            # hands; check once instead of spamming at the sampler rate.
            # Motor calibration only: the estimate is motor-derived, so a
            # missing encoder anchor is irrelevant to it.
            try:
                self._estimate_ok = bool(
                    self.hand.is_calibrated(use_joint_feedback=False))
            except Exception:
                self._estimate_ok = False
            if not self._estimate_ok:
                logger.warning(
                    "motor calibration incomplete — joint estimate disabled "
                    "(run orca_core's calibration first)")
        return self._estimate_ok

    def _joint_estimate(self, motor_pos) -> dict | None:
        pos = self.hand._motor_to_joint_pos(motor_pos)
        return {j: v for j, v in pos.items() if v is not None}

    def estimate_joints(self) -> dict | None:
        """Naive motor-derived joint angles in degrees (the 'ghost' pose)."""
        if not self.caps.motors or not self._estimate_allowed():
            return None
        return self._joint_estimate(self.hand.get_motor_pos())

    def motor_snapshot(self) -> tuple[dict | None, dict | None]:
        """``(joint estimate, per-motor currents)`` from one bus read — they
        share a register block, so asking separately costs two round trips."""
        if not self.caps.motors:
            return None, None
        state = self.hand.get_motor_state()
        currents = dict(zip(self.hand.config.motor_ids, state.current))
        if not self._estimate_allowed():
            return None, currents
        return self._joint_estimate(state.position), currents

    def loop_correction(self) -> dict | None:
        return self.hand.get_loop_correction() if self.caps.feedback_loop else None

    def loop_stats(self) -> dict | None:
        return self.hand.get_loop_stats() if self.caps.feedback_loop else None

    def encoder_stats(self):
        client = self._encoder_client or getattr(self.hand, "_encoder_client", None)
        return client.get_stats() if client else None

    def encoder_reading(self):
        """Latest raw encoder auto-stream frame, or None."""
        client = self._encoder_client or getattr(self.hand, "_encoder_client", None)
        return client.get_latest() if client else None

    def sensing_link_health(self) -> dict:
        """``{"encoder": LinkHealth, "tactile": LinkHealth}`` for whichever
        sensing links this session has open (they may be the same port)."""
        out: dict = {}
        for name, getter in (("encoder", "get_encoder_link_health"),
                             ("tactile", "get_tactile_link_health")):
            fn = getattr(self.hand, getter, None)
            if fn is None:
                continue
            try:
                health = fn()
            except Exception:
                health = None
            if health is not None:
                out[name] = health
        # Sensors-only sessions own the encoder link themselves.
        if "encoder" not in out and self._encoder_client is not None:
            link = self._encoder_client._link
            out["encoder"] = LinkHealth(
                connected=link.is_connected, port_dead=link.is_port_dead,
                port_error=link.port_error, stats=link.get_link_stats())
        return out

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


def connect_session(settings: UiSettings, config,
                    presence: HardwarePresence | None = None) -> HandSession:
    """Connect at the best achievable tier.

    ``presence`` may be supplied by a caller that has already probed (the
    supervisor does, because the same probe decides which model ``config``
    is); left out, this probes for itself.
    """
    declared = declared_capabilities(config, settings.engage_feedback,
                                     motors_enabled=settings.motors_enabled)

    if settings.mock:
        return _connect_mock(settings, config, declared)

    if presence is None:
        presence = probe_hardware(config)
    sensing_present = bool(presence.sensing.tactile or presence.sensing.encoder)

    if settings.motors_enabled and presence.motor_port:
        try:
            return _connect_with_motors(settings, config, declared, presence)
        except SessionConnectError as motor_error:
            # A motor port that answers but won't connect (unpowered motors,
            # broken motor stack) must not block sensor viewing.
            if not sensing_present:
                raise
            logger.warning("all motor tiers failed — trying sensors-only")
            try:
                return _connect_sensors_only(settings, config, declared, presence)
            except SessionConnectError as sensor_error:
                raise SessionConnectError(
                    "motor tiers and sensors-only both failed",
                    attempts=motor_error.attempts + sensor_error.attempts
                    + [str(sensor_error)],
                )
    if sensing_present:
        return _connect_sensors_only(settings, config, declared, presence)
    busy = presence.busy_ports
    raise SessionConnectError(
        "No ORCA hardware found (no motor bus, tactile, or encoder port)."
        + (f" {', '.join(busy)} is held by another process — close it and "
           "reconnect." if busy else "")
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


def _connect_mock(settings: UiSettings, config, declared: dict) -> HandSession:
    from orca_ui.mock import build_mock_hand

    # The config in force, not settings.config_path: the model can be changed
    # from the browser, and the mock has to simulate the hand now selected.
    hand = build_mock_hand(config.config_path,
                           engage_feedback=settings.engage_feedback)
    try:
        ok, msg = hand.connect(interactive=False)
    except (JointFeedbackConnectError, RuntimeError) as e:
        raise SessionConnectError(f"mock connect failed: {e}")
    if not ok:
        raise SessionConnectError(f"mock connect failed: {msg}")
    return HandSession(
        hand=hand,
        caps=_caps_from_hand(hand, declared),
        tier="mock",
        message=msg,
        ports={"motor": "mock", "tactile": "mock", "encoder": "mock"},
    )


def _build_hand(settings: UiSettings, config, feedback: bool, tactile: bool):
    """Fresh hand instance for one ladder rung (never reuse across attempts).

    Always built from ``config`` — settings.config_path is only where the
    process *started*, and the supervisor may since have swapped the model to
    match the hand that is actually plugged in.
    """
    if feedback and not tactile and isinstance(config, OrcaHandTouchConfig):
        # No factory entry for 'feedback hand from a touch config': construct
        # directly; OrcaHandJointFeedback ignores the sensors block.
        return OrcaHandJointFeedback(config=config)
    if not feedback and not tactile and isinstance(config, OrcaHandTouchConfig):
        return OrcaHand(config=config)
    return load_hand(config_path=config.config_path,
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
        if presence.motor_port and \
                getattr(getattr(hand, "config", None), "port", None) == "auto":
            # Discovery already resolved the motor port — scoped to the pinned
            # board when one is pinned. Left as "auto", connect() re-resolves
            # it machine-globally: ambiguous with two adapters attached, and
            # with a board pinned it must not look beyond that board at all.
            # In-memory only; persist_resolved_driver diffs against the file,
            # so a patched port is never written back.
            import copy

            if hand.config is config:
                # Never mutate the supervisor's shared config object.
                hand.config = copy.copy(config)
            object.__setattr__(hand.config, "port", presence.motor_port)
        try:
            ok, msg = hand.connect(interactive=False)
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
    hand = load_hand(config_path=config.config_path, engage_feedback=False)
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

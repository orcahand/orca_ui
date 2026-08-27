"""Facade the API layer talks to: validation, torque gating, command routing.

Owns the supervisor and command worker. Every mutating call validates the
current session's capabilities and raises :class:`ServiceError` with an HTTP
status code the REST layer forwards verbatim.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from orca_core import JointGains

from pathlib import Path

from orca_ui.core_source import resolve_cached as resolve_core_source
from orca_ui.hand import zeroing
from orca_ui.hand.commands import CommandWorker
from orca_ui.hand.presets import BUILTIN_POSES, BUILTIN_SEQUENCES
from orca_ui.hand.sessions import HandSession
from orca_ui.hand.states import ControlSource
from orca_ui.hand.supervisor import HandSupervisor, model_name_of
from orca_ui.library import Library, LibraryError
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)

TACTILE_MODES = {
    "resultant": (True, False),
    "taxels": (False, True),
    "combined": (True, True),
}

# Direct motor moves are clamped to this distance from the current position
# per command — sliders nudge, they don't teleport.
MAX_DIRECT_MOTOR_STEP_RAD = 0.8

# One-shot moves (apply pose, go neutral): distance-scaled glide instead of a
# fixed duration, so a far target never starts at whip speed.
_MOVE_SPEED_DEG_S = 90.0
_MOVE_STEP_S = 0.02
_MOVE_MIN_S = 0.5
_MOVE_MAX_S = 3.0

# Dynamixel X-series Hardware Error Status bits. Any latched bit makes the
# motor refuse to energize until rebooted. The UI decodes the bits to human-readable names for display.
_HW_ERROR_BITS = (
    (0x01, "input_voltage"),
    (0x04, "overheating"),
    (0x08, "motor_encoder"),
    (0x10, "electrical_shock"),
    (0x20, "overload"),
)


def _decode_hw_error(value: int | None) -> list[str] | None:
    if value is None:
        return None
    return [name for bit, name in _HW_ERROR_BITS if value & bit]


def _gain_entry(kp: float, ki: float, correction_max_deg: float) -> dict:
    """One control channel's PI settings, as the API serializes them."""
    return JointGains(kp=float(kp), ki=float(ki),
                      correction_max_deg=float(correction_max_deg)).as_dict()


def _uniform_gains(joint_gains: dict[str, dict]) -> dict | None:
    """The one gain set every loop joint shares, or None when they differ."""
    entries = list(joint_gains.values())
    if not entries or any(entry != entries[0] for entry in entries[1:]):
        return None
    return dict(entries[0])


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _encoder_sensed_joints(config) -> list[str]:
    """Joints with an encoder measurement, wrist included.

    Config-only mirror of orca_core's ``OrcaHand.encoder_backed_joints`` (the
    two agree joint for joint), so ``hand_info`` can describe the hand before
    a session exists.
    """
    from orca_core.hardware.sensing.constants import (
        ENCODER_JOINTS_ALL,
        JOINT_TO_ENCODER_SLOT,
    )

    configured = config.joint_encoder_joints
    if not configured:
        return []
    available = [
        joint for joint in JOINT_TO_ENCODER_SLOT
        if joint in config.joint_to_motor_map
    ]
    if any(str(j).lower() == ENCODER_JOINTS_ALL for j in configured):
        return available
    configured_set = set(configured)
    return [joint for joint in available if joint in configured_set]


class HandService:
    def __init__(
        self,
        settings: UiSettings,
        publish_status: Callable[[dict], None] | None = None,
        publish_error: Callable[[str], None] | None = None,
        publish_topic: Callable[[str, dict], None] | None = None,
    ):
        self.settings = settings
        self._publish_status = publish_status or (lambda snapshot: None)
        self._publish_error = publish_error or (lambda message: None)
        self._publish_topic = publish_topic or (lambda topic, payload: None)

        self._state_lock = threading.Lock()
        self._targets: dict[str, float] = {}
        self._direct_motor_mode = False
        self._tactile_mode = "combined"
        self._control_source = ControlSource.MANUAL
        self._control_owner_label = ControlSource.MANUAL.value
        self._operation_manager = None   # attached post-construction (server.py)
        self._sweeper = None             # mock-only dev sweeper, for estop
        self._teleop_manager = None      # attached post-construction (server.py)
        self._teleop_installer = None    # ditto; exists even with teleop off
        # Gains connect() installed from config.yaml — what "reset" restores.
        # Live gains are read back from the controller, never shadowed here.
        self._config_gains: dict[str, dict] = {}

        self.supervisor = HandSupervisor(
            settings,
            on_status=lambda snapshot: self._publish_status(snapshot.as_dict()),
            on_session_ready=self._session_ready,
            on_error=self._publish_error,
            on_model_changed=self._model_changed,
        )
        self.worker = CommandWorker(
            get_session=lambda: self.supervisor.session,
            on_error=self._publish_error,
        )
        self._max_current = int(self.supervisor.config.max_current)

        self._library_root = (
            Path(settings.library_dir) if settings.library_dir
            else Path.home() / ".orca_ui" / "library"
        )
        self.library = Library(self._library_root, self.supervisor.model_name)

    # ----- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self.supervisor.start()
        self.worker.start()

    def stop(self) -> None:
        self.worker.shutdown()
        self.supervisor.shutdown()

    # ----- reads -------------------------------------------------------------

    @property
    def session(self) -> HandSession | None:
        return self.supervisor.session

    def status(self) -> dict:
        return self.supervisor.status().as_dict()

    def hand_info(self) -> dict:
        config = self.supervisor.config
        encoder_backed = set(_encoder_sensed_joints(config))
        session = self.session
        # Which sensed joints can actually be decoded: raw counts become joint
        # angles only with a per-joint anchor from the calibration sweep.
        encoder_calibrated = None
        if session is not None:
            try:
                encoder_calibrated = set(
                    session.hand.calibration.joint_encoder_calibration_dict or {})
            except Exception:
                encoder_calibrated = None
        # loop_controlled: True = the feedback loop closes on this joint;
        # False = the loop skipped it at connect (incomplete calibration) and
        # it runs open-loop; None = not applicable (no loop at this tier, or
        # the joint has no encoder to close on).
        loop_joints: set | None = None
        loop_skipped: set = set()
        if session is not None and session.caps.feedback_loop:
            try:
                loop_joints = set(session.hand.loop_joint_names or [])
                loop_skipped = set(session.hand.loop_skipped_joints)
            except Exception:
                loop_joints = None
                loop_skipped = set()
        # Encoder-measured travel vs the config nominal, and which ROM frame
        # the joint↔motor map currently runs in ("anchor" or "centered").
        measured_roms: dict = {}
        effective_roms: dict = {}
        rom_frame = None
        if session is not None:
            try:
                measured_roms = dict(
                    session.hand.calibration.joint_roms_measured_dict or {})
                effective_roms = dict(session.hand.effective_joint_roms_dict)
                rom_frame = session.hand.rom_frame
            except Exception:
                measured_roms, effective_roms, rom_frame = {}, {}, None

        def _rom_delta(joint: str) -> float | None:
            measured = measured_roms.get(joint)
            if measured is None:
                return None
            lower, upper = config.joint_roms_dict[joint]
            return float(
                (measured[1] - measured[0]) - (float(upper) - float(lower)))

        joints = [
            {
                "id": joint,
                # Which motor drives it — the only place the UI can turn a
                # motor id from telemetry back into something a human names.
                "motor_id": config.joint_to_motor_map.get(joint),
                "rom": [float(v) for v in config.joint_roms_dict[joint]],
                "rom_measured": (
                    [float(v) for v in measured_roms[joint]]
                    if joint in measured_roms else None
                ),
                "rom_delta": _rom_delta(joint),
                "rom_effective": (
                    [float(v) for v in effective_roms[joint]]
                    if joint in measured_roms and joint in effective_roms
                    else None
                ),
                "neutral": float(config.neutral_position.get(joint, 0.0)),
                "encoder_backed": joint in encoder_backed,
                "encoder_calibrated": (
                    None if encoder_calibrated is None or joint not in encoder_backed
                    else joint in encoder_calibrated
                ),
                "loop_controlled": (
                    True if loop_joints is not None and joint in loop_joints
                    else False if joint in loop_skipped
                    else None
                ),
            }
            for joint in config.joint_ids
        ]
        info = {
            "model_name": model_name_of(config),
            "side": config.type,
            "mock": self.settings.mock,
            "rom_frame": rom_frame,
            "joints": joints,
            "calibration": self._calibration_state(
                session, encoder_backed, encoder_calibrated),
            "control": self.control_state(),
            "core": resolve_core_source().as_dict(),
        }
        mapping = getattr(config, "finger_to_sensor_id", None)
        if mapping:
            info["finger_to_sensor_id"] = dict(mapping)
        tactile_config = session.tactile_configuration() if session else None
        if tactile_config is not None:
            info["tactile"] = {
                "active_sensors": list(tactile_config.active_sensors),
                "num_taxels": dict(tactile_config.num_taxels),
            }
        return info

    def _calibration_state(self, session, encoder_backed: set,
                           encoder_calibrated: set | None) -> dict:
        """Motor vs joint-feedback calibration, and what recalibrating fixes.

        ``needs_calibration`` is the single flag the UI gates its "calibrate
        the hand" prompt on, and ``hint`` is the matching sentence. Two states
        set them: nothing recorded at all, and motors recorded but encoder
        anchors missing (where every calibration taken before the wrist joined
        the loop lands). The first is the one worth surfacing loudly — the
        connect ladder has already dropped to a non-feedback tier by then, so
        joint sensing is gone from the UI with no other explanation.
        """
        config = self.supervisor.config
        state: dict = {"motors": None, "joint_feedback": None,
                       "missing_anchors": [], "needs_calibration": False,
                       "hint": None,
                       # config.yaml defaults for the sweep's hardstop
                       # current — what a per-run override replaces.
                       "calibration_current":
                           int(getattr(config, "calibration_current", 0))
                           or None,
                       "wrist_calibration_current":
                           int(getattr(config, "wrist_calibration_current", 0))
                           or None}
        if session is None or not session.caps.motors:
            return state
        try:
            state["motors"] = bool(
                session.hand.is_calibrated(use_joint_feedback=False))
        except Exception:
            return state
        if encoder_backed and encoder_calibrated is not None:
            missing = [joint for joint in session.hand.config.joint_ids
                       if joint in encoder_backed
                       and joint not in encoder_calibrated]
            state["missing_anchors"] = missing
            state["joint_feedback"] = bool(state["motors"]) and not missing
        if not state["motors"]:
            # Motor limits, ratios and encoder anchors all come out of the
            # same sweep, so an uncalibrated hand has one thing to say.
            state["needs_calibration"] = True
            state["hint"] = (
                "hand is not calibrated — run Setup → Calibrate to record "
                + ("motor limits and the joint-encoder anchors"
                   if encoder_backed else "the motor limits")
            )
        elif state["missing_anchors"]:
            missing = state["missing_anchors"]
            state["needs_calibration"] = True
            state["hint"] = (
                f"no encoder anchor for {', '.join(missing)} — recalibrate "
                f"{'them' if len(missing) > 1 else 'it'} to capture the "
                "anchor; until then the joint runs open-loop"
            )
        return state

    def _live_gains(self) -> dict[str, dict]:
        """Per-joint PI gains the running loop is actually using. Empty when
        no loop runs — the source of truth is the controller, not the UI."""
        session = self.session
        if session is None or not session.caps.feedback_loop:
            return {}
        try:
            return {joint: gains.as_dict()
                    for joint, gains in session.hand.get_pid_gains().items()}
        except Exception:
            return {}

    def control_state(self) -> dict:
        joint_gains = self._live_gains()
        with self._state_lock:
            return {
                "torque_enabled": self.supervisor.status().torque_enabled,
                "max_current": self._max_current,
                # The one gain set every loop joint shares, or null when the
                # joints are tuned individually.
                "gains": _uniform_gains(joint_gains),
                "joint_gains": joint_gains,
                # What connect() installed from config.yaml — reset restores it.
                "config_gains": {joint: dict(gains)
                                 for joint, gains in self._config_gains.items()},
                "tactile_mode": self._tactile_mode,
                "control_source": self._control_source.value,
                "control_owner": self._control_owner_label,
                "direct_motor_mode": self._direct_motor_mode,
            }

    def stats(self) -> dict:
        session = self.session
        out: dict = {"loop": None, "tactile": None, "encoder": None,
                     "command": self.worker.stats()}
        if session is None:
            return out
        try:
            out["loop"] = session.loop_stats()
        except Exception:
            pass
        tactile = session.tactile_stats()
        if tactile is not None:
            out["tactile"] = {
                "frames_ok": tactile.frames_ok,
                "frames_bad_payload_size": tactile.frames_bad_payload_size,
                "frames_bad_payload": tactile.frames_bad_payload,
                "last_error_code": tactile.last_error_code,
                "stream_rearms": tactile.stream_rearms,
            }
        encoder = session.encoder_stats()
        if encoder is not None:
            out["encoder"] = {
                "frames_ok": encoder.frames_ok,
                "last_freshness_ms": encoder.last_freshness_ms,
            }
        return out

    # ----- session bootstrap ---------------------------------------------------

    def _model_changed(self, config) -> None:
        """The supervisor swapped in the model the hardware reports (a hand
        that was off at startup, or a different one plugged in since). Repoint
        everything keyed by model; the browser refetches ``/hand/info`` off
        the model field in the status stream."""
        self._max_current = int(config.max_current)
        # Poses and recordings are per-model — a left hand's library must not
        # follow the right hand that replaced it.
        self.library = Library(self._library_root, model_name_of(config))

    def _session_ready(self, session: HandSession) -> None:
        # connect() builds a new controller on the config's gains, so last
        # session's tuning is gone from the hardware — snapshot what it
        # actually installed as the set "reset" returns to.
        config_gains = self._live_gains()
        with self._state_lock:
            self._targets = {}
            # Fresh session, fresh (unpaused) loop: a stale armed flag must
            # not survive the reconnect and block joint targets.
            self._direct_motor_mode = False
            self._config_gains = config_gains
        self._publish_control_state()
        if session.caps.tactile:
            try:
                zeroing.apply_saved_offsets(session)
                resultant, taxels = TACTILE_MODES[self._tactile_mode]
                session.start_tactile_stream(resultant=resultant, taxels=taxels)
            except Exception as e:
                logger.exception("tactile stream autostart failed")
                self._publish_error(f"tactile stream start failed: {e}")

    # ----- validation helpers --------------------------------------------------

    def _require_session(self) -> HandSession:
        session = self.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        return session

    def _require_motors(self) -> HandSession:
        session = self._require_session()
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        return session

    def _require_feedback(self) -> HandSession:
        session = self._require_motors()
        if not session.caps.feedback_loop:
            raise ServiceError("joint-feedback loop not running", status_code=409)
        return session

    def _require_tactile(self) -> HandSession:
        session = self._require_session()
        if not session.caps.tactile:
            raise ServiceError("no tactile sensors in this session", status_code=409)
        return session

    def _require_torque(self) -> HandSession:
        session = self._require_motors()
        if not self.supervisor.status().torque_enabled:
            raise ServiceError("torque is disabled — enable it first", status_code=409)
        return session

    def require_manual_control(self) -> None:
        """409 unless MANUAL owns the joint-target channel. Public: the
        operation manager gates op starts on it (an operation or teleop
        session must not be yanked by another control session starting)."""
        with self._state_lock:
            source = self._control_source
            owner = self._control_owner_label
        if source != ControlSource.MANUAL:
            raise ServiceError(
                f"control is owned by {owner} — stop it first", status_code=409)

    # Backwards-compatible private alias (existing call sites).
    _require_manual_control = require_manual_control

    # ----- control-source arbiter -------------------------------------------------

    @property
    def control_source(self) -> ControlSource:
        with self._state_lock:
            return self._control_source

    def acquire_control(self, source: ControlSource,
                        owner_label: str | None = None) -> None:
        """Take ownership of the joint-target channel (one owner at a time)."""
        with self._state_lock:
            if self._control_source != ControlSource.MANUAL:
                raise ServiceError(
                    f"control is owned by {self._control_owner_label}",
                    status_code=409)
            self._control_source = source
            self._control_owner_label = owner_label or source.value
        # A new owner streams joint targets; a paused loop would silently
        # ignore them for loop joints.
        self._exit_direct_motor_mode()
        self._publish_control_state()

    def release_control(self, expected: ControlSource | None = None) -> None:
        """Return the channel to MANUAL. With ``expected`` set, a release from
        a stale owner (e.g. a teleop disengage racing an operation start) is a
        logged no-op instead of stomping the new owner."""
        with self._state_lock:
            if expected is not None and self._control_source != expected:
                logger.info("release_control(%s) ignored — owner is %s",
                            expected.value, self._control_source.value)
                return
            self._control_source = ControlSource.MANUAL
            self._control_owner_label = ControlSource.MANUAL.value
        self._publish_control_state()

    # ----- operations / e-stop ------------------------------------------------------

    def attach_operation_manager(self, manager) -> None:
        self._operation_manager = manager

    def attach_sweeper(self, sweeper) -> None:
        self._sweeper = sweeper

    def attach_teleop_manager(self, manager) -> None:
        self._teleop_manager = manager

    def attach_teleop_installer(self, installer) -> None:
        self._teleop_installer = installer

    @property
    def operation_manager(self):
        return self._operation_manager

    @property
    def teleop_manager(self):
        return getattr(self, "_teleop_manager", None)

    @property
    def teleop_installer(self):
        # Present even when teleop_manager is None (--no-teleop): fetching the
        # checkout is exactly what an install-less console needs to offer.
        return getattr(self, "_teleop_installer", None)

    def estop(self) -> dict:
        """Best-effort emergency stop: never raises.

        Stops the active operation (whose own cleanup handles op-owned
        hardware, e.g. a maintenance calibrate disables torque on its own
        hand), disables torque on the supervisor session if one exists, and
        stops the mock sweeper. Reports what was actioned.
        """
        report: dict = {}
        teleop = self.teleop_manager
        if teleop is not None:
            # First: teleop is the one source still streaming new motion.
            try:
                report["teleop_stopped"] = teleop.estop()
            except Exception as e:
                logger.exception("estop: teleop stop failed")
                report["teleop_stopped"] = False
                report["teleop_error"] = str(e)
        manager = self._operation_manager
        if manager is not None:
            try:
                report["operation_stopped"] = manager.stop(estop=True)
            except Exception as e:
                logger.exception("estop: operation stop failed")
                report["operation_stopped"] = False
                report["operation_error"] = str(e)
        self._exit_direct_motor_mode()
        try:
            session = self.session
            if session is not None and session.caps.motors:
                session.hand.disable_torque()
                self.supervisor.set_torque_flag(False)
                self.worker.reset()
                self._publish_control_state()
                report["torque_disabled"] = True
            else:
                report["torque_disabled"] = False
        except Exception as e:
            logger.exception("estop: disable_torque failed")
            report["torque_disabled"] = False
            report["torque_error"] = str(e)
        sweeper = self._sweeper
        if sweeper is not None:
            try:
                sweeper.stop()
                report["sweeper_stopped"] = True
            except Exception:
                logger.exception("estop: sweeper stop failed")
                report["sweeper_stopped"] = False
        return report

    # ----- motor control ---------------------------------------------------------

    def _publish_control_state(self) -> None:
        from orca_ui.streaming import topics as T
        self._publish_topic(T.CONTROL_STATE, self.control_state())

    def enable_torque(self, *, from_operation: bool = False) -> dict:
        """``from_operation`` skips the manual-control gate: the running
        operation owns the control source, so a demo enabling torque for
        itself is not a second client fighting the owner."""
        session = self._require_motors()
        if not from_operation:
            self._require_manual_control()
        if session.caps.feedback_loop:
            # Re-anchor first so enabling torque never lurches toward a stale
            # target (the hand may have been posed by hand while limp).
            session.hand.rebase_loop()
        session.hand.enable_torque()
        self.supervisor.set_torque_flag(True)
        seed = self._current_pose(session)
        # The hand may have been posed by hand while limp: the interpolator
        # must ramp out of where it actually is, not where it last drove to.
        self.worker.reset(seed)
        with self._state_lock:
            self._targets = dict(seed)
        self._publish_control_state()
        self._publish_targets()
        return {"seed": seed}

    def disable_torque(self) -> None:
        session = self._require_motors()
        session.hand.disable_torque()
        self.supervisor.set_torque_flag(False)
        self.worker.reset()
        self._publish_control_state()

    def _current_pose(self, session: HandSession) -> dict:
        measured = session.measured_joints()
        if measured:
            return {j: float(v) for j, v in measured.items()}
        estimate = session.estimate_joints()
        return {j: float(v) for j, v in (estimate or {}).items()}

    def current_pose(self) -> dict:
        """Best current joint pose (degrees): measured, else the motor-derived
        estimate, else the last accepted targets. Used as the teleop ramp-in
        start pose; empty dict when nothing is known."""
        session = self.session
        pose = self._current_pose(session) if session is not None else {}
        if pose:
            return pose
        with self._state_lock:
            return dict(self._targets)

    def set_targets(self, angles: dict[str, float],
                    source: ControlSource = ControlSource.MANUAL) -> None:
        """Write joint targets. Validation (joints, torque) and the
        ``joints.target`` echo apply to every source; only the current
        control-source owner may write."""
        session = self._require_torque()
        with self._state_lock:
            current = self._control_source
            owner = self._control_owner_label
            direct = self._direct_motor_mode
        if direct:
            raise ServiceError(
                "direct motor mode is armed — joint targets are suspended "
                "(loop writes paused); disarm it first", status_code=409)
        if source != current:
            raise ServiceError(
                f"joint targets are owned by {owner}", status_code=409)
        known = set(session.hand.config.joint_ids)
        unknown = set(angles) - known
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        clean = {j: float(v) for j, v in angles.items()}
        self.worker.submit_targets(clean)
        with self._state_lock:
            self._targets.update(clean)
        self._publish_targets()

    def _publish_targets(self) -> None:
        from orca_ui.streaming import topics as T
        with self._state_lock:
            targets = dict(self._targets)
        if targets:
            self._publish_topic(T.JOINTS_TARGET, {"angles": targets})

    def calibrate_joint_manual(self, joint: str, angle_deg: float) -> dict:
        """Re-anchor one joint's encoder calibration at an operator-verified
        angle (matched by eye against the 3D model).

        Quick and per-joint: samples the encoder at the current pose and
        rewrites only this joint's anchor. Works at any tier that can reach
        the encoder stream — the session's own client when it has one, else a
        temporary client on the probed encoder port (the first-time case,
        where missing anchors kept the feedback tier from connecting).
        """
        session = self.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        self._require_manual_control()
        config = self.supervisor.config
        if joint not in _encoder_sensed_joints(config):
            raise ServiceError(f"{joint} has no joint encoder")
        rom = config.joint_roms_dict.get(joint)
        if rom and not (rom[0] <= float(angle_deg) <= rom[1]):
            raise ServiceError(
                f"angle {angle_deg:.1f}° is outside the ROM "
                f"[{rom[0]}, {rom[1]}] of {joint}")

        client = (session._encoder_client
                  or getattr(session.hand, "_encoder_client", None))
        temp_client = temp_link = None
        if client is None:
            from orca_ui.hand.operations import hand_ops

            port = session.ports.get("encoder")
            if not port or port == "mock":
                raise ServiceError(
                    "no encoder stream in this session — plug in / power the "
                    "sensing board and reconnect", status_code=409)
            try:
                temp_client, temp_link = hand_ops.open_encoder_client_on_port(
                    config, port)
            except Exception as e:
                raise ServiceError(f"encoder stream unavailable: {e}",
                                   status_code=409)
            client = temp_client
        try:
            anchor = session.hand.calibrate_joint_encoder_manual(
                joint, float(angle_deg), joint_encoder_client=client)
        except ValueError as e:
            raise ServiceError(str(e))
        except Exception as e:
            # Sampling timeout / chip-flagged stream / persist failure.
            raise ServiceError(f"manual calibration of {joint} failed: {e}",
                               status_code=409)
        finally:
            if temp_client is not None:
                from orca_ui.hand.operations import hand_ops

                hand_ops.close_encoder_client(temp_client, temp_link)
        loop_updated = bool(
            session.caps.feedback_loop
            and joint in (session.hand.loop_joint_names or []))
        measured = (session.measured_joints() or {}).get(joint)
        logger.info("manual joint calibration: %s anchored at %.2f° "
                    "(anchor_count=%d, loop_updated=%s)",
                    joint, angle_deg, anchor, loop_updated)
        return {
            "joint": joint,
            "angle_deg": float(angle_deg),
            "anchor_count": int(anchor),
            "loop_updated": loop_updated,
            "measured_deg": None if measured is None else float(measured),
        }

    def go_neutral(self) -> None:
        session = self._require_torque()
        self._require_manual_control()
        neutral = {j: float(v)
                   for j, v in session.hand.config.neutral_position.items()}
        num_steps = self._move_steps(session, neutral)
        self.worker.submit_op(
            lambda: session.hand.set_neutral_position(
                num_steps=num_steps, step_size=_MOVE_STEP_S))
        with self._state_lock:
            self._targets.update(neutral)
        self._publish_targets()

    def _move_steps(self, session, target: dict[str, float]) -> int:
        """Interpolation step count for a one-shot move, scaled to the
        distance so a far pose glides instead of snapping: the fixed-duration
        default turns a 90° travel into a tendon-whipping start."""
        try:
            current = session.sampled_joints() or {}
        except Exception:
            current = {}
        jump = max((abs(v - current[j]) for j, v in target.items()
                    if j in current), default=0.0)
        duration = min(_MOVE_MAX_S,
                       max(_MOVE_MIN_S, jump / _MOVE_SPEED_DEG_S))
        return max(1, round(duration / _MOVE_STEP_S))

    # ----- feedback-loop gains -------------------------------------------------
    #
    # The loop's controller carries one PI channel per loop-controlled joint,
    # each with its own gains (config.yaml's ``joint_control_gains`` seeds
    # them at connect). Joints the loop doesn't close on — connect-time skips
    # and joints without an encoder — have no channel at all, so no gain
    # applies to them. Live gains always come from the controller.

    def _loop_joints(self, session: HandSession) -> list[str]:
        """Joints the loop closes on, in the controller's channel order."""
        names = session.hand.loop_joint_names
        if not names:
            raise ServiceError("joint loop controls no joints",
                               status_code=409)
        return list(names)

    def _resolve_loop_joints(self, session: HandSession,
                             joints: list[str]) -> list[str]:
        names = self._loop_joints(session)
        unknown = sorted(set(joints) - set(names))
        if unknown:
            raise ServiceError(
                f"joints not under the feedback loop (gains do not apply): "
                f"{unknown}; tunable joints: {names}")
        return list(dict.fromkeys(joints))

    def set_gains(self, kp: float, ki: float, correction_max_deg: float,
                  joints: list[str] | None = None) -> None:
        """Retune the outer PI loop.

        ``joints=None`` writes one gain set to every loop joint; a joint list
        writes exactly those joints and leaves the rest as they are.
        """
        session = self._require_feedback()
        entry = _gain_entry(kp, ki, correction_max_deg)
        if joints is None:
            # Scalars: orca_core broadcasts them across every channel.
            session.hand.set_pid_gains(
                Kp=entry["kp"], Ki=entry["ki"],
                correction_max_deg=entry["correction_max_deg"])
        else:
            targets = self._resolve_loop_joints(session, joints)

            def named(key: str) -> dict[str, float]:
                return {joint: entry[key] for joint in targets}

            session.hand.set_pid_gains(
                Kp=named("kp"), Ki=named("ki"),
                correction_max_deg=named("correction_max_deg"))
        self._publish_control_state()

    def reset_gains(self, joints: list[str] | None = None) -> None:
        """Restore the config gains connect() installed — for every loop joint,
        or just ``joints``."""
        session = self._require_feedback()
        names = (self._loop_joints(session) if joints is None
                 else self._resolve_loop_joints(session, joints))
        with self._state_lock:
            config_gains = dict(self._config_gains)
        restore = {joint: config_gains[joint] for joint in names
                   if joint in config_gains}
        if not restore:
            raise ServiceError("no config gains recorded for this session",
                               status_code=409)

        def named(key: str) -> dict[str, float]:
            return {joint: gains[key] for joint, gains in restore.items()}

        session.hand.set_pid_gains(
            Kp=named("kp"), Ki=named("ki"),
            correction_max_deg=named("correction_max_deg"))
        self._publish_control_state()

    def gains_state(self) -> dict:
        """Live gains for every loop-controlled joint, the config gains reset
        returns to, and the joints that run open-loop (no PI channel)."""
        session = self._require_feedback()
        names = self._loop_joints(session)
        live = self._live_gains()
        with self._state_lock:
            config_gains = dict(self._config_gains)
        controlled = set(names)
        return {
            "joints": [
                {
                    "joint": joint,
                    "modified": (joint in config_gains
                                 and live.get(joint) != config_gains[joint]),
                    **live.get(joint, {}),
                }
                for joint in names
            ],
            "config_gains": config_gains,
            "open_loop_joints": [joint for joint in session.hand.config.joint_ids
                                 if joint not in controlled],
        }

    def set_max_current(self, ma: int) -> None:
        import dataclasses

        session = self._require_motors()
        session.hand.set_max_current(ma)
        session.hand.config = dataclasses.replace(session.hand.config,
                                                  max_current=ma)
        with self._state_lock:
            self._max_current = int(ma)
        self._publish_control_state()

    def rebase(self) -> None:
        session = self._require_feedback()
        session.hand.rebase_loop()

    def set_rom_frame(self, mode: str) -> dict:
        """Switch how measured joint travel is laid onto the config ROM
        ("anchor" = classic upper-pinned, "centered" = measured delta split
        equally onto both ends). Applies to estimates and encoder decode
        immediately; a running feedback loop keeps its snapshot until
        reconnect."""
        session = self.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        self._require_manual_control()
        try:
            session.hand.set_rom_frame(mode)
        except ValueError as e:
            raise ServiceError(str(e))
        logger.info("rom frame set to %s", mode)
        return {
            "rom_frame": mode,
            "requires_reconnect": bool(session.caps.feedback_loop),
        }

    # ----- direct motor control (advanced diagnostics) -----------------------
    #
    # Raw motor-space access for bring-up/diagnosis (e.g. a single motor that
    # refuses to turn). Deliberately friction-ful: an explicit arm step that
    # pauses the feedback loop's writes, per-move step clamp, and joint
    # targets 409 while armed.

    def motor_snapshot(self) -> dict:
        """Per-motor position + latched hardware-error state.

        Reads happen under the loop-write fence (when a loop runs) so the
        per-motor status round-trips don't interleave with 100 Hz writes on
        the shared bus.
        """
        from contextlib import nullcontext

        session = self._require_motors()
        hand = session.hand
        fence = getattr(hand, "_loop_writes_paused", None)
        with (fence() if fence is not None else nullcontext()):
            positions = hand.get_motor_pos(as_dict=True)
            read_error = getattr(
                getattr(hand, "_motor_client", None), "read_hardware_error", None)
            errors: dict = {}
            for mid in hand.config.motor_ids:
                err = None
                if read_error is not None:
                    try:
                        err = read_error(mid)
                    except Exception:
                        err = None
                errors[mid] = err
        motor_to_joint = hand.config.motor_to_joint_dict
        with self._state_lock:
            direct = self._direct_motor_mode
        return {
            "direct_mode": direct,
            "max_step_rad": MAX_DIRECT_MOTOR_STEP_RAD,
            "motors": [
                {
                    "id": int(mid),
                    "joint": str(motor_to_joint.get(mid, "")),
                    "position": float(positions[mid]),
                    "hw_error": errors[mid],
                    "hw_error_flags": _decode_hw_error(errors[mid]),
                }
                for mid in hand.config.motor_ids
            ],
        }

    def set_direct_motor_mode(self, enabled: bool, *,
                              from_operation: bool = False) -> dict:
        """``from_operation`` skips the manual-control gate: a motor-space
        replay owns the control source and arms/disarms around its run."""
        session = self._require_motors()
        if not from_operation:
            self._require_manual_control()
        if not enabled:
            self._exit_direct_motor_mode()
            return {"direct_mode": False}
        loop = getattr(session.hand, "_loop", None)
        with self._state_lock:
            already = self._direct_motor_mode
            self._direct_motor_mode = True
        if not already and loop is not None:
            # The loop would immediately overwrite raw motor writes for its
            # joints; fence it out for the whole armed window.
            loop.pause_writes()
        self._publish_control_state()
        return {"direct_mode": True}

    def _exit_direct_motor_mode(self) -> None:
        """Disarm + resume loop writes. Safe to call from any state; never
        raises (used by estop and control-source handover)."""
        with self._state_lock:
            was = self._direct_motor_mode
            self._direct_motor_mode = False
        if not was:
            return
        session = self.session
        loop = getattr(session.hand, "_loop", None) if session else None
        if loop is not None:
            try:
                loop.resume_writes()
            except Exception:
                logger.exception("resume_writes failed leaving direct motor mode")
        self._publish_control_state()

    def set_motor_position(self, motor_id: int, position: float) -> dict:
        """Raw motor-space position write (radians) for one motor."""
        import math

        session = self._require_torque()
        self._require_manual_control()
        with self._state_lock:
            if not self._direct_motor_mode:
                raise ServiceError(
                    "direct motor mode is not armed", status_code=409)
        hand = session.hand
        motor_id = int(motor_id)
        if motor_id not in hand.config.motor_ids:
            raise ServiceError(f"unknown motor id {motor_id}")
        position = float(position)
        if not math.isfinite(position):
            raise ServiceError("position must be finite")
        current = float(hand.get_motor_pos(as_dict=True)[motor_id])
        if abs(position - current) > MAX_DIRECT_MOTOR_STEP_RAD:
            raise ServiceError(
                f"refusing a {abs(position - current):.2f} rad move — direct "
                f"moves are capped at {MAX_DIRECT_MOTOR_STEP_RAD} rad from "
                "the current position")
        # The hardware motor client divides positions by its scale — needs
        # an array, not a list.
        hand.write_motor_pos([motor_id], np.asarray([position]))
        return {"id": motor_id, "position": position, "previous": current}

    # ----- poses & demos -------------------------------------------------------

    def list_poses(self) -> list[dict]:
        user = self.library.user_poses()
        out = []
        for name in BUILTIN_POSES:
            if name in user:
                continue   # user pose shadows the built-in
            out.append({"name": name, "builtin": True, "placeholder": True})
        for name, entry in user.items():
            out.append({
                "name": name, "builtin": False, "placeholder": False,
                "saved_at": entry.get("saved_at"),
            })
        out.sort(key=lambda p: p["name"])
        return out

    def save_pose(self, name: str, angles: dict[str, float]) -> None:
        known = set(self.supervisor.config.joint_ids)
        unknown = set(angles) - known
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        try:
            self.library.save_pose(name, angles)
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)

    def delete_pose(self, name: str) -> None:
        try:
            self.library.delete_pose(name)
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)

    def capture_pose(self, name: str) -> dict:
        session = self._require_session()
        measured = session.sampled_joints()
        if not measured:
            raise ServiceError(
                "no joint angles available — capture needs joint encoders, "
                "or motors with a completed calibration",
                status_code=409)
        angles = {j: round(float(v), 2) for j, v in measured.items()}
        self.save_pose(name, angles)
        return {"name": name, "angles": angles}

    def apply_pose(self, name: str) -> dict:
        """One-shot interpolated move to a saved/built-in pose. Not an
        operation — finishes in one motion, needs no progress/stop."""
        from orca_ui.hand.operations import hand_ops

        session = self._require_torque()
        self._require_manual_control()
        user = self.library.user_poses()
        if name in user:
            angles = {j: float(v)
                      for j, v in (user[name].get("angles") or {}).items()}
        elif name in BUILTIN_POSES:
            angles = hand_ops.pose_from_fractions(
                session.hand, BUILTIN_POSES[name])
        else:
            raise ServiceError(f"no pose named {name!r}", status_code=404)
        if not angles:
            raise ServiceError(f"pose {name!r} is empty")
        num_steps = self._move_steps(session, angles)
        self.worker.submit_op(
            lambda: session.hand.set_joint_positions(
                angles, num_steps=num_steps, step_size=_MOVE_STEP_S))
        with self._state_lock:
            self._targets.update(angles)
        self._publish_targets()
        return {"name": name, "angles": angles}

    def list_demos(self) -> dict[str, list[dict[str, float]]]:
        from orca_ui.hand.operations import hand_ops

        demos = dict(hand_ops.demo_definitions())
        demos.update(BUILTIN_SEQUENCES)
        return demos

    def demos_listing(self) -> list[dict]:
        from orca_ui.hand.operations import hand_ops

        core = hand_ops.demo_definitions()
        out = []
        for name, poses in self.list_demos().items():
            out.append({
                "name": name,
                "poses": len(poses),
                "source": "orca_core" if name in core else "orca_ui",
            })
        out.sort(key=lambda d: d["name"])
        return out

    def delete_trajectory(self, name: str) -> None:
        try:
            self.library.delete_trajectory(name)
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)

    # ----- tactile ---------------------------------------------------------------

    def set_tactile_mode(self, mode: str) -> None:
        if mode not in TACTILE_MODES:
            raise ServiceError(f"invalid mode: {mode!r} "
                               f"(expected {sorted(TACTILE_MODES)})")
        session = self._require_tactile()
        resultant, taxels = TACTILE_MODES[mode]
        session.stop_tactile_stream()
        session.start_tactile_stream(resultant=resultant, taxels=taxels)
        with self._state_lock:
            self._tactile_mode = mode
        self._publish_control_state()

    @property
    def tactile_mode(self) -> str:
        with self._state_lock:
            return self._tactile_mode

    def zero_tactile(self, num_samples: int = 100) -> None:
        session = self._require_tactile()
        zeroing.capture_and_persist(session, num_samples=num_samples)

    def clear_tactile_zero(self) -> None:
        session = self._require_tactile()
        zeroing.clear_offsets(session)

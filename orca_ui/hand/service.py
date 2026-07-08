"""Facade the API layer talks to: validation, torque gating, command routing.

Owns the supervisor and command worker. Every mutating call validates the
current session's capabilities and raises :class:`ServiceError` with an HTTP
status code the REST layer forwards verbatim.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable

from orca_core.control.constants import (
    DEFAULT_CORRECTION_MAX_DEG,
    DEFAULT_KI,
    DEFAULT_KP,
)

from pathlib import Path

from orca_ui.hand import zeroing
from orca_ui.hand.commands import CommandWorker
from orca_ui.hand.presets import BUILTIN_POSES, BUILTIN_SEQUENCES
from orca_ui.hand.sessions import HandSession
from orca_ui.hand.states import ControlSource
from orca_ui.hand.supervisor import HandSupervisor
from orca_ui.library import Library, LibraryError
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)

TACTILE_MODES = {
    "resultant": (True, False),
    "taxels": (False, True),
    "combined": (True, True),
}


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _encoder_sensed_joints(config) -> list[str]:
    """Joints with an encoder measurement, wrist included.

    Production hands wire encoders on all 17 slots. orca_core's
    ``_encoder_backed_joints`` excludes the wrist because it stays outside
    the closed loop — a control policy, not a sensing limitation — so the
    UI keeps its own list for what can be *displayed* as measured.
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
        self._tactile_mode = "combined"
        self._control_source = ControlSource.MANUAL
        self._control_owner_label = ControlSource.MANUAL.value
        self._operation_manager = None   # attached post-construction (server.py)
        self._sweeper = None             # mock-only dev sweeper, for estop
        self._gains = {
            "kp": DEFAULT_KP,
            "ki": DEFAULT_KI,
            "correction_max_deg": DEFAULT_CORRECTION_MAX_DEG,
        }

        self.supervisor = HandSupervisor(
            settings,
            on_status=lambda snapshot: self._publish_status(snapshot.as_dict()),
            on_session_ready=self._session_ready,
            on_error=self._publish_error,
        )
        self.worker = CommandWorker(
            get_session=lambda: self.supervisor.session,
            on_error=self._publish_error,
        )
        self._max_current = int(self.supervisor.config.max_current)

        library_root = (
            Path(settings.library_dir) if settings.library_dir
            else Path.home() / ".orca_ui" / "library"
        )
        model_name = os.path.basename(
            os.path.dirname(self.supervisor.config.config_path))
        self.library = Library(library_root, model_name)

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
        joints = [
            {
                "id": joint,
                "rom": [float(v) for v in config.joint_roms_dict[joint]],
                "neutral": float(config.neutral_position.get(joint, 0.0)),
                "encoder_backed": joint in encoder_backed,
                "encoder_calibrated": (
                    None if encoder_calibrated is None or joint not in encoder_backed
                    else joint in encoder_calibrated
                ),
            }
            for joint in config.joint_ids
        ]
        info = {
            "model_name": os.path.basename(os.path.dirname(config.config_path)),
            "side": config.type,
            "mock": self.settings.mock,
            "joints": joints,
            "control": self.control_state(),
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

    def control_state(self) -> dict:
        with self._state_lock:
            return {
                "torque_enabled": self.supervisor.status().torque_enabled,
                "max_current": self._max_current,
                "gains": dict(self._gains),
                "tactile_mode": self._tactile_mode,
                "control_source": self._control_source.value,
                "control_owner": self._control_owner_label,
            }

    def stats(self) -> dict:
        session = self.session
        out: dict = {"loop": None, "tactile": None, "encoder": None}
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

    def _session_ready(self, session: HandSession) -> None:
        with self._state_lock:
            self._targets = {}
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

    def _require_manual_control(self) -> None:
        with self._state_lock:
            source = self._control_source
            owner = self._control_owner_label
        if source != ControlSource.MANUAL:
            raise ServiceError(
                f"control is owned by {owner} — stop it first", status_code=409)

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
        self._publish_control_state()

    def release_control(self) -> None:
        with self._state_lock:
            self._control_source = ControlSource.MANUAL
            self._control_owner_label = ControlSource.MANUAL.value
        self._publish_control_state()

    # ----- operations / e-stop ------------------------------------------------------

    def attach_operation_manager(self, manager) -> None:
        self._operation_manager = manager

    def attach_sweeper(self, sweeper) -> None:
        self._sweeper = sweeper

    @property
    def operation_manager(self):
        return self._operation_manager

    def estop(self) -> dict:
        """Best-effort emergency stop: never raises.

        Stops the active operation (whose own cleanup handles op-owned
        hardware, e.g. a maintenance calibrate disables torque on its own
        hand), disables torque on the supervisor session if one exists, and
        stops the mock sweeper. Reports what was actioned.
        """
        report: dict = {}
        manager = self._operation_manager
        if manager is not None:
            try:
                report["operation_stopped"] = manager.stop(estop=True)
            except Exception as e:
                logger.exception("estop: operation stop failed")
                report["operation_stopped"] = False
                report["operation_error"] = str(e)
        try:
            session = self.session
            if session is not None and session.caps.motors:
                session.hand.disable_torque()
                self.supervisor.set_torque_flag(False)
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

    def enable_torque(self) -> dict:
        session = self._require_motors()
        self._require_manual_control()
        if session.caps.feedback_loop:
            # Re-anchor first so enabling torque never lurches toward a stale
            # target (the hand may have been posed by hand while limp).
            session.hand.rebase_loop()
        session.hand.enable_torque()
        self.supervisor.set_torque_flag(True)
        seed = self._current_pose(session)
        with self._state_lock:
            self._targets = dict(seed)
        self._publish_control_state()
        self._publish_targets()
        return {"seed": seed}

    def disable_torque(self) -> None:
        session = self._require_motors()
        session.hand.disable_torque()
        self.supervisor.set_torque_flag(False)
        self._publish_control_state()

    def _current_pose(self, session: HandSession) -> dict:
        measured = session.measured_joints()
        if measured:
            return {j: float(v) for j, v in measured.items()}
        estimate = session.estimate_joints()
        return {j: float(v) for j, v in (estimate or {}).items()}

    def set_targets(self, angles: dict[str, float],
                    source: ControlSource = ControlSource.MANUAL) -> None:
        """Write joint targets. Validation (joints, torque) and the
        ``joints.target`` echo apply to every source; only the current
        control-source owner may write."""
        session = self._require_torque()
        with self._state_lock:
            current = self._control_source
            owner = self._control_owner_label
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

    def go_neutral(self) -> None:
        session = self._require_torque()
        self._require_manual_control()
        self.worker.submit_op(session.hand.set_neutral_position)
        with self._state_lock:
            self._targets.update({
                j: float(v)
                for j, v in session.hand.config.neutral_position.items()
            })
        self._publish_targets()

    def set_gains(self, kp: float, ki: float, correction_max_deg: float,
                  i_clamp_deg: float | None = None) -> None:
        session = self._require_feedback()
        session.hand.set_pid_gains(
            Kp=kp, Ki=ki,
            correction_max_deg=correction_max_deg,
            i_clamp_deg=i_clamp_deg,
        )
        with self._state_lock:
            self._gains = {"kp": kp, "ki": ki,
                           "correction_max_deg": correction_max_deg}
        self._publish_control_state()

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
        measured = session.measured_joints()
        if not measured:
            raise ServiceError(
                "no measured joint angles — capture needs encoders",
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
        self.worker.submit_op(
            lambda: session.hand.set_joint_positions(
                angles, num_steps=25, step_size=0.02))
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

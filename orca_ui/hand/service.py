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

from orca_ui.hand import zeroing
from orca_ui.hand.commands import CommandWorker
from orca_ui.hand.sessions import HandSession
from orca_ui.hand.supervisor import HandSupervisor
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


def _encoder_backed_joints(config) -> list[str]:
    """Config-level mirror of ``OrcaHand._encoder_backed_joints`` (usable
    before any hand instance exists)."""
    from orca_core.hardware.sensing.constants import (
        ENCODER_JOINTS_ALL,
        JOINT_TO_ENCODER_SLOT,
    )

    configured = config.joint_encoder_joints
    if not configured:
        return []
    available = [
        joint for joint in JOINT_TO_ENCODER_SLOT
        if joint != "wrist" and joint in config.joint_to_motor_map
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
    ):
        self.settings = settings
        self._publish_status = publish_status or (lambda snapshot: None)
        self._publish_error = publish_error or (lambda message: None)

        self._state_lock = threading.Lock()
        self._tactile_mode = "combined"
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
        encoder_backed = set(_encoder_backed_joints(config))
        joints = [
            {
                "id": joint,
                "rom": [float(v) for v in config.joint_roms_dict[joint]],
                "neutral": float(config.neutral_position.get(joint, 0.0)),
                "encoder_backed": joint in encoder_backed,
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
        session = self.session
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

    # ----- motor control ---------------------------------------------------------

    def enable_torque(self) -> dict:
        session = self._require_motors()
        if session.caps.feedback_loop:
            # Re-anchor first so enabling torque never lurches toward a stale
            # target (the hand may have been posed by hand while limp).
            session.hand.rebase_loop()
        session.hand.enable_torque()
        self.supervisor.set_torque_flag(True)
        return {"seed": self._current_pose(session)}

    def disable_torque(self) -> None:
        session = self._require_motors()
        session.hand.disable_torque()
        self.supervisor.set_torque_flag(False)

    def _current_pose(self, session: HandSession) -> dict:
        measured = session.measured_joints()
        if measured:
            return {j: float(v) for j, v in measured.items()}
        estimate = session.estimate_joints()
        return {j: float(v) for j, v in (estimate or {}).items()}

    def set_targets(self, angles: dict[str, float]) -> None:
        session = self._require_torque()
        known = set(session.hand.config.joint_ids)
        unknown = set(angles) - known
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        self.worker.submit_targets({j: float(v) for j, v in angles.items()})

    def go_neutral(self) -> None:
        session = self._require_torque()
        self.worker.submit_op(session.hand.set_neutral_position)

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

    def set_max_current(self, ma: int) -> None:
        import dataclasses

        session = self._require_motors()
        session.hand.set_max_current(ma)
        session.hand.config = dataclasses.replace(session.hand.config,
                                                  max_current=ma)
        with self._state_lock:
            self._max_current = int(ma)

    def rebase(self) -> None:
        session = self._require_feedback()
        session.hand.rebase_loop()

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
